import streamlit as st
import google.generativeai as genai
from youtube_transcript_api import YouTubeTranscriptApi
import yt_dlp
import os
import time
from jinja2 import Template
import re

# --- GÜVENLİK VE AYARLAR ---
try:
    API_KEY = st.secrets["GEMINI_API_KEY"]
except:
    API_KEY = "BURAYA_API_KEY_GELECEK"

genai.configure(api_key=API_KEY)
model = genai.GenerativeModel('gemini-2.5-flash')

# --- YARDIMCI FONKSİYONLAR ---

def html_olustur(veri, dil):
    # Şablon kontrolü
    if not os.path.exists("sablon.html"):
        st.error("⚠️ Şablon dosyası (sablon.html) eksik! Lütfen GitHub'a yükleyin.")
        return None

    with open("sablon.html", "r", encoding="utf-8") as f:
        sablon_metni = f.read()
    
    template = Template(sablon_metni)
    
    risk_durumu = "guvenli"
    if "RİSKLİ" in veri['karar'].upper() or "RISKY" in veri['karar'].upper():
        risk_durumu = "riskli"
    
    html_cikti = template.render(
        dil_kodu=dil,
        baslik=veri['baslik'],
        ozet=veri['ozet'],
        karar_basligi=veri['karar'],
        karar_metni=veri['karar_detay'],
        sinif_adi=risk_durumu,
        detayli_icerik=veri['icerik'].replace("\n", "<br>"),
        diger_dil_linki=veri['diger_link'],
        diger_dil_ismi="English" if dil == "tr" else "Türkçe"
    )
    
    return html_cikti

def sesi_indir_ve_yukle(video_url):
    dosya_adi = f"temp_{int(time.time())}"
    
    # --- YOUTUBE MASKELEME AYARLARI ---
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': f'{dosya_adi}.%(ext)s',
        'noplaylist': True,
        'quiet': True,
        'nocheckcertificate': True,
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-us,en;q=0.5',
        }
    }
    
    indirilen_dosya = f"{dosya_adi}.m4a"
    st.info("☁️ Sunucu videoyu işliyor... (YouTube engeli aşılmaya çalışılıyor)")
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
            ext = info.get('ext', 'm4a')
            indirilen_dosya = f"{dosya_adi}.{ext}"
            
        st.text("📤 Gemini'ye aktarılıyor...")
        uploaded_file = genai.upload_file(path=indirilen_dosya)
        
        while uploaded_file.state.name == "PROCESSING":
            time.sleep(2)
            uploaded_file = genai.get_file(uploaded_file.name)
            
        # Temizlik
        if os.path.exists(indirilen_dosya):
            os.remove(indirilen_dosya)
            
        return uploaded_file
    except Exception as e:
        st.warning(f"Ses indirilemedi. Sebep: {e}")
        if os.path.exists(indirilen_dosya):
            try: os.remove(indirilen_dosya)
            except: pass
        return None

def analiz_motoru(video_url):
    if "v=" in video_url: video_id = video_url.split("v=")[1].split("&")[0]
    elif "youtu.be" in video_url: video_id = video_url.split("/")[-1]
    else: video_id = video_url

    prompt_metni = """
    Sen uzman bir Pedagog ve SEO uzmanısın. İçeriği analiz et ve 2 dilde rapor ver.
    Format (AYRAC ile böl):
    1. KISIM: TÜRKÇE RAPOR
    BAŞLIK: (Başlık)
    URL: (kisa-url)
    KARAR: (GÜVENLİ/RİSKLİ)
    ÖZET: (Özet)
    İÇERİK: (Detay)
    ---AYRAC---
    2. KISIM: İNGİLİZCE RAPOR
    TITLE: (Title)
    URL: (url)
    VERDICT: (SAFE/RISKY)
    SUMMARY: (Summary)
    CONTENT: (Content)
    """

    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['tr', 'en'])
        text = " ".join([i['text'] for i in transcript])
        final_prompt = f"Metin:\n{text[:20000]}\n\n{prompt_metni}"
        st.success("✅ Altyazı bulundu, hızlı analiz yapılıyor...")
        response = model.generate_content(final_prompt)
        return response.text
    except:
        st.warning("⚠️ Altyazı yok, ses analizi deneniyor...")
        ses_dosyasi = sesi_indir_ve_yukle(video_url)
        if ses_dosyasi:
            response = model.generate_content([prompt_metni, ses_dosyasi])
            return response.text
        else:
            return "HATA: Video işlenemedi. YouTube sunucu engeli koymuş olabilir. Sadece altyazılı videoları deneyin."

# --- ARAYÜZ ---
st.set_page_config(page_title="Pedagog AI", page_icon="🛡️")
st.title("🛡️ AI Ebeveyn Asistanı")
st.markdown("Videoyu yapıştır, güvenli mi öğren.")

url_input = st.text_input("YouTube Linki:")

if st.button("Analiz Et"):
    if url_input:
        with st.spinner('Analiz yapılıyor...'):
            ham_sonuc = analiz_motoru(url_input)
            
            if "HATA" in ham_sonuc:
                st.error(ham_sonuc)
            else:
                try:
                    parts = ham_sonuc.split("---AYRAC---")
                    tr_kisim, en_kisim = parts[0], parts[1]
                    
                    tr_baslik = tr_kisim.split("BAŞLIK:")[1].split("\n")[0].strip()
                    tr_ozet = tr_kisim.split("ÖZET:")[1].split("İÇERİK:")[0].strip()
                    tr_karar = tr_kisim.split("KARAR:")[1].split("\n")[0].strip()
                    tr_icerik = tr_kisim.split("İÇERİK:")[1].strip()
                    
                    st.divider()
                    if "GÜVENLİ" in tr_karar.upper():
                        st.success(f"✅ {tr_karar}")
                    else:
                        st.error(f"🚨 {tr_karar}")
                    
                    st.write(f"**{tr_baslik}**")
                    st.info(tr_ozet)
                    
                    html_tr = html_olustur({
                        'baslik': tr_baslik, 'ozet': tr_ozet, 'karar': tr_karar, 
                        'karar_detay': 'Sonuç', 'icerik': tr_icerik, 'diger_link': '#', 'url_slug': 'rapor'
                    }, "tr")
                    
                    if html_tr:
                        st.download_button("🇹🇷 Raporu İndir", data=html_tr, file_name="analiz.html", mime="text/html")
                        
                except Exception as e:
                    st.error(f"Sonuç okunamadı: {e}")
