import streamlit as st
import google.generativeai as genai
from youtube_transcript_api import YouTubeTranscriptApi
import yt_dlp
import os
import time
from jinja2 import Template
import re

# --- AYARLAR ---
API_KEY = "AIzaSyC40X3rKqddGeN83BwRXMGgJqjn6OMlLNs"
genai.configure(api_key=API_KEY)

# Model Seçimi
model = genai.GenerativeModel('gemini-2.5-flash')

# --- ÖNBELLEK KLASÖRÜ ---
# İndirilen sesleri burada saklayacağız
CACHE_FOLDER = "ses_deposu"
if not os.path.exists(CACHE_FOLDER):
    os.makedirs(CACHE_FOLDER)

# --- YARDIMCI FONKSİYONLAR ---

def url_yap(baslik):
    """Başlığı URL dostu hale getirir"""
    baslik = str(baslik).lower().replace("ı", "i").replace("ğ", "g").replace("ü", "u").replace("ş", "s").replace("ö", "o").replace("ç", "c")
    return re.sub(r'[^a-z0-9-]', '-', baslik).strip('-')

def html_olustur(veri, dil):
    """Verileri şablonla birleştirip HTML dosyası kaydeder"""
    if not os.path.exists("sablon.html"):
        st.error("🚨 HATA: 'sablon.html' dosyası bulunamadı!")
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
    
    dosya_adi = f"{veri['url_slug']}.html"
    with open(dosya_adi, "w", encoding="utf-8") as f:
        f.write(html_cikti)
    
    return dosya_adi

def sesi_indir_ve_yukle(video_url, video_id):
    """
    Önce depoya bakar, varsa oradan alır. Yoksa indirir.
    """
    # Hedef dosya yolu: ses_deposu/VIDEO_ID.m4a
    yerel_dosya_yolu = os.path.join(CACHE_FOLDER, f"{video_id}.m4a")
    
    dosya_mevcut = False
    
    # 1. KONTROL: Dosya zaten var mı?
    if os.path.exists(yerel_dosya_yolu):
        st.success("⚡ Hafızada kayıtlı ses bulundu! Tekrar indirilmiyor...")
        dosya_mevcut = True
    else:
        # Dosya yoksa indir
        st.info("📥 Dosya hafızada yok, YouTube'dan indiriliyor... (Biraz sürebilir)")
        ydl_opts = {
            'format': 'bestaudio[ext=m4a]',
            'outtmpl': os.path.join(CACHE_FOLDER, f'{video_id}.%(ext)s'), # ID ile kaydet
            'noplaylist': True,
            'quiet': True
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])
            dosya_mevcut = True
        except Exception as e:
            st.error(f"İndirme hatası: {e}")
            return None

    # 2. GEMINI'YE YÜKLEME
    # Dosya elimizde (ya yeni indi ya eskiden vardı), şimdi Gemini'ye atalım
    if dosya_mevcut:
        try:
            st.text("📤 Ses Gemini'ye gönderiliyor...")
            uploaded_file = genai.upload_file(path=yerel_dosya_yolu)
            
            while uploaded_file.state.name == "PROCESSING":
                time.sleep(1)
                uploaded_file = genai.get_file(uploaded_file.name)
            
            return uploaded_file
        except Exception as e:
            st.error(f"Gemini yükleme hatası: {e}")
            return None
    return None

def analiz_motoru(video_url):
    # Video ID'yi en başta buluyoruz (Kimlik Kartı)
    if "v=" in video_url:
        video_id = video_url.split("v=")[1].split("&")[0]
    elif "youtu.be" in video_url:
        video_id = video_url.split("/")[-1]
    else:
        video_id = video_url

    prompt_metni = """
    Sen uzman bir Pedagog ve SEO uzmanısın.
    GÖREV: Bu içeriği analiz et ve 2 FARKLI DİLDE rapor hazırla.
    
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

    # 1. YÖNTEM: Transkript (En Hızlısı)
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['tr', 'en'])
        text = " ".join([i['text'] for i in transcript])
        final_prompt = f"Metin:\n{text[:20000]}\n\n{prompt_metni}"
        response = model.generate_content(final_prompt)
        return response.text

    except Exception:
        # 2. YÖNTEM: Ses Analizi (Akıllı Depolama Modu)
        # video_id'yi de gönderiyoruz ki klasörde arayabilsin
        ses_dosyasi = sesi_indir_ve_yukle(video_url, video_id)
        
        if ses_dosyasi:
            st.text("🧠 Gemini sesi dinliyor...")
            response = model.generate_content([prompt_metni, ses_dosyasi])
            
            # NOT: Artık dosyayı silmiyoruz (os.remove yok), depoda kalsın.
            return response.text
        else:
            return "HATA: Ses işlenemedi."

# --- ARAYÜZ ---
st.set_page_config(page_title="İçerik Fabrikası Pro", page_icon="⚡", layout="wide")

st.title("⚡ Akıllı İçerik Fabrikası")
st.caption("Aynı videoyu tekrar indirmez, hafızadan kullanır.")

col1, col2 = st.columns([4, 1])
with col1:
    url_input = st.text_input("YouTube Linki:")
with col2:
    st.write("")
    st.write("")
    btn = st.button("ANALİZ ET", type="primary")

if btn and url_input:
    with st.spinner('Analiz başlatılıyor...'):
        ham_sonuc = analiz_motoru(url_input)
        
        if "HATA" in ham_sonuc:
            st.error(ham_sonuc)
        else:
            try:
                parts = ham_sonuc.split("---AYRAC---")
                tr_kisim = parts[0]
                en_kisim = parts[1]
                
                # Basit parser
                tr_veri = {
                    'baslik': tr_kisim.split("BAŞLIK:")[1].split("\n")[0].strip(),
                    'url_slug': tr_kisim.split("URL:")[1].split("\n")[0].strip(),
                    'karar': tr_kisim.split("KARAR:")[1].split("\n")[0].strip(),
                    'karar_detay': "Pedagog Analiz Sonucu",
                    'ozet': tr_kisim.split("ÖZET:")[1].split("İÇERİK:")[0].strip(),
                    'icerik': tr_kisim.split("İÇERİK:")[1].strip(),
                    'diger_link': "#"
                }
                en_veri = {
                    'baslik': en_kisim.split("TITLE:")[1].split("\n")[0].strip(),
                    'url_slug': en_kisim.split("URL:")[1].split("\n")[0].strip(),
                    'karar': en_kisim.split("VERDICT:")[1].split("\n")[0].strip(),
                    'karar_detay': "Pedagogue Analysis Result",
                    'ozet': en_kisim.split("SUMMARY:")[1].split("CONTENT:")[0].strip(),
                    'icerik': en_kisim.split("CONTENT:")[1].strip(),
                    'diger_link': f"{tr_veri['url_slug']}.html"
                }
                tr_veri['diger_link'] = f"{en_veri['url_slug']}.html"

                dosya_tr = html_olustur(tr_veri, "tr")
                dosya_en = html_olustur(en_veri, "en")

                # Dashboard
                st.divider()
                c1, c2 = st.columns(2)
                with c1:
                    st.subheader("🇹🇷 Türkçe")
                    if "GÜVENLİ" in tr_veri['karar']:
                        st.success(tr_veri['karar'])
                    else:
                        st.error(tr_veri['karar'])
                    st.write(tr_veri['baslik'])
                    st.markdown(f"`{dosya_tr}`")
                
                with c2:
                    st.subheader("🇺🇸 English")
                    if "SAFE" in en_veri['karar']:
                        st.success(en_veri['karar'])
                    else:
                        st.error(en_veri['karar'])
                    st.write(en_veri['baslik'])
                    st.markdown(f"`{dosya_en}`")
                
                st.balloons()
                
            except Exception as e:
                st.error(f"Hata: {e}")
                st.text(ham_sonuc)