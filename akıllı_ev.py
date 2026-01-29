import streamlit as st
import openai
import json
import requests
import time
import threading
import speech_recognition as sr
from dotenv import load_dotenv
import os
from streamlit_mic_recorder import mic_recorder
import io

# --- 1. SAYFA AYARLARI ---
st.set_page_config(
    page_title="ÇETİN AI Ev Asistanı", 
    page_icon="🏠", 
    layout="wide", 
    initial_sidebar_state="expanded"
)

# --- 2. TASARIM (CSS) ---
st.markdown("""
<style>
    h1 { color: #FF4B4B; font-family: 'Helvetica Neue', sans-serif; text-align: center; }
    div[data-testid="stMetric"] { background-color: #262730; border: 1px solid #464b5f; padding: 15px; border-radius: 10px; color: white; }
    div.stButton > button { width: 100%; border-radius: 10px; height: 50px; font-weight: bold; }
    .stChatMessage { border-radius: 15px; padding: 10px; }
    .streamlit-expanderHeader { font-size: 16px; font-weight: bold; color: #FF4B4B; }
</style>
""", unsafe_allow_html=True)

# --- AYARLAR ---
load_dotenv()
GROK_API_KEY = os.getenv("GROK_API_KEY")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
HA_URL = os.getenv("HA_URL")
HA_TOKEN = os.getenv("HA_TOKEN")

if not GROK_API_KEY:
    st.error("⚠️ GROK_API_KEY eksik! Streamlit Secrets ayarlarını kontrol et.")
    st.stop()

client = openai.OpenAI(api_key=GROK_API_KEY, base_url="https://api.x.ai/v1")

# --- ENTITY TANIMLARI ---
ENTITY_NAMES = {
    "light.salon_isigi": "🛋️ Salon Işığı",
    "light.yatak_odasi_isigi": "🛏️ Yatak Odası Işığı",
    "light.mutfak_isigi": "🍳 Mutfak Işığı",
    "climate.klima": "❄️/🔥 Klima",
    "fan.fan_salon": "🌀 Salon Fanı",
    "cover.perde_salon": "🪟 Salon Perdesi",
    "media_player.tv_salon": "📺 Salon TV",
    "media_player.muzik_sistemi": "🎵 Müzik Sistemi",
    "switch.kahve_makinesi": "☕ Kahve Makinesi",
    "switch.cay_makinesi": "🍵 Çay Makinesi",
    "switch.robot_supurge": "🧹 Robot Süpürge",
    "scene.sabah_rutini": "🌅 Sabah Rutini",
    "scene.aksam_rahatlama": "🌙 Akşam Rahatlama",
    "scene.film_gecesi": "🎬 Film Gecesi",
    "scene.misafir_modu": "👨‍👩‍👧‍👦 Misafir Modu",
    "scene.calisma_modu": "💻 Çalışma Modu",
    "scene.enerji_tasarrufu": "🔋 Enerji Tasarrufu"
}

# --- KATEGORİLİ KOMUT LİSTESİ (HEM SES HEM YAZI İÇİN REHBER) ---
COMMAND_CATEGORIES = {
    "💡 Aydınlatma": [
        "Salon ışığını aç",
        "Salon ışığını kapat",
        "Yatak odası ışığını %10 yap (Gece Modu)",
        "Mutfak ışığını kapat",
        "Tüm ışıkları kapat"
    ],
    "🌡️ İklim & Konfor": [
        "Klimayı 22 derece yap",
        "Klimayı kapat",
        "Fanı çalıştır",
        "Salon perdesini aç",
        "Salon perdesini kapat"
    ],
    "📺 Medya & Ev Aletleri": [
        "Televizyonu aç",
        "Müzik sistemini başlat",
        "Robot süpürgeyi çalıştır",
        "Kahve makinesini aç",
        "Çay demle (Makineyi aç)"
    ],
    "🎬 Senaryolar (Tek Tuşla)": [
        "Film modunu başlat (Işıklar kısılır, TV açılır)",
        "Sabah rutinini başlat (Perde, Kahve)",
        "Akşam rahatlama moduna geç",
        "Misafir modu (Tüm ışıklar açık)",
        "Enerji tasarrufu yap (Gereksizleri kapat)"
    ],
    "🧠 Akıllı / Koşullu Komutlar": [
        "30 dakika sonra salon ışığını kapat",
        "Hava durumuna göre evin sıcaklığını ayarla",
        "Eğer dışarı soğuksa klimayı ısıtmaya al",
        "Eğer hareket yoksa ışıkları kapat",
        "Her sabah 8'de kahvemi hazırla"
    ]
}

# Dropdown için düz liste oluşturma
ALL_COMMANDS_FLAT = ["👇 Listeden Bir Komut Seçin..."]
for category, commands in COMMAND_CATEGORIES.items():
    for cmd in commands:
        ALL_COMMANDS_FLAT.append(f"[{category}] {cmd}")

# --- FONKSİYONLAR ---
def get_real_temperature():
    if OPENWEATHER_API_KEY:
        try:
            url = f"http://api.openweathermap.org/data/2.5/weather?q=Ankara&appid={OPENWEATHER_API_KEY}&units=metric&lang=tr"
            response = requests.get(url, timeout=3).json()
            if response.get("main"):
                temp = response['main']['temp']
                desc = response['weather'][0]['description']
                hum = response['main'].get('humidity', 50)
                wind = response['wind'].get('speed', 10)
                return temp, desc, hum, wind
        except:
            pass
    return 22.0, "parçalı bulutlu (simülasyon)", 45, 12

def transcribe_audio_free(audio_bytes):
    r = sr.Recognizer()
    try:
        audio_file = io.BytesIO(audio_bytes)
        with sr.AudioFile(audio_file) as source:
            audio_data = r.record(source)
            text = r.recognize_google(audio_data, language="tr-TR")
            return text
    except:
        return None 

def send_to_ha(action):
    entity_id = action.get("entity_id")
    if not entity_id: return "Hata: Cihaz ID yok"
    
    device_name = ENTITY_NAMES.get(entity_id, entity_id)

    if HA_URL and HA_TOKEN:
        try:
            domain = entity_id.split('.')[0]
            service = "turn_on" if action.get("state") in ["on", "open"] else "turn_off"
            url = f"{HA_URL}/api/services/{domain}/{service}"
            headers = {"Authorization": f"Bearer {HA_TOKEN}", "Content-Type": "application/json"}
            payload = {"entity_id": entity_id}
            for k, v in action.items():
                if k not in ["entity_id", "state"]:
                    payload[k] = v
            requests.post(url, headers=headers, json=payload, timeout=2)
            return f"✅ **HA (Gerçek):** {device_name} İletildi"
        except Exception as e:
            return f"❌ HA Hatası: {str(e)}"
            
    state_str = "AÇILDI 🟢" if action.get("state") in ["on", "open"] else "KAPATILDI 🔴"
    if "scene" in entity_id: state_str = "AKTİF EDİLDİ 🎬"
    
    details = []
    if "brightness_pct" in action: details.append(f"%{action['brightness_pct']} Parlaklık")
    if "temperature" in action: details.append(f"{action['temperature']}°C")
    
    detail_str = f"({', '.join(details)})" if details else ""
    return f"🛠️ **SİMÜLASYON:** {device_name} → {state_str} {detail_str}"

def process_timer(entity_id, delay, action):
    time.sleep(delay)
    res = send_to_ha({"entity_id": entity_id, **action})
    print(f"Zamanlayıcı Bitti: {res}")

# --- AKIŞ KONTROLÜ ---
if "page" not in st.session_state: st.session_state.page = "welcome"
if "user_name" not in st.session_state: st.session_state.user_name = ""

# --- SAYFA 1: KARŞILAMA ---
if st.session_state.page == "welcome":
    st.title("🏠 ÇETİN AI Ev Asistanı")
    st.markdown("---")
    with st.expander("ℹ️ Bu Uygulama Nedir ve Nasıl Kullanılır? (Okumak için Tıklayın)", expanded=False):
        st.markdown("""
        ### 📱 Uygulama Ne İşe Yarar?
        ÇETİN AI, klasik akıllı ev sistemlerinin aksine, sizinle **konuşarak anlaşan** ve **düşünebilen** yeni nesil bir ev asistanıdır.
        
        ### 🚀 Nasıl Kullanılır?
        1.  **Başlatın:** Aşağıdaki butona basın.
        2.  **Tanışın:** Adınızı girin.
        3.  **Emir Verin:**
            * **Seçerek:** Hazır listeden bir görev seçin.
            * **Konuşarak:** Mikrofonla "Işıkları aç" deyin.
            * **Yazarak:** Derdinizi anlatın.
        """)
    st.write("")
    col_center = st.columns([1, 2, 1])
    with col_center[1]:
        if st.button("Uygulamayı Başlatın 🚀"):
            st.session_state.page = "name_input"
            st.rerun()

# --- SAYFA 2: İSİM GİRİŞİ ---
elif st.session_state.page == "name_input":
    st.title("👋 Hoş Geldiniz")
    st.markdown("---")
    with st.form("user_name_form"):
        st.subheader("Size nasıl hitap etmemi istersiniz?")
        name_input = st.text_input("Adınız:", value="", placeholder="Örn: Ahmet Bey")
        if st.form_submit_button("Sisteme Giriş Yap ✅") and name_input.strip():
            st.session_state.user_name = name_input.strip().split()[0]
            st.session_state.page = "main_app"
            st.rerun()

# --- SAYFA 3: ANA UYGULAMA ---
elif st.session_state.page == "main_app":
    # --- SIDEBAR (SESLİ KOMUT REHBERİ) ---
    with st.sidebar:
        st.image("https://cdn-icons-png.flaticon.com/512/4712/4712035.png", width=80)
        st.title("ÇETİN AI Panel")
        
        st.write("🎙️ **Sesli Komut**")
        audio = mic_recorder(start_prompt="🔴 Konuş (Bas-Çek)", stop_prompt="⏹ Bitir", key="recorder")
        
        decoded_text = None
        if audio:
            with st.spinner("Sesiniz işleniyor..."):
                decoded_text = transcribe_audio_free(audio["bytes"])
            if decoded_text: st.success(f"Algılanan: '{decoded_text}'")
            else: st.warning("Ses anlaşılamadı.")

        st.markdown("---")
        
        # SESLİ KOMUT REHBERİ (DETAYLI GÖRÜNÜM)
        st.info("🗣️ **Neler Söyleyebilirim?**")
        with st.expander("Tüm Yeteneklerimi Gör (Tıkla)", expanded=True):
            for cat, cmds in COMMAND_CATEGORIES.items():
                st.markdown(f"**{cat}**")
                for c in cmds:
                    st.caption(f"- {c}")
        
        st.markdown("---")
        if st.button("🚪 Uygulamadan Ayrıl"):
            st.session_state.page = "welcome"
            st.session_state.user_name = ""
            st.session_state.messages = []
            st.rerun()

    # --- DASHBOARD ---
    st.title(f"🏠 ÇETİN AI Ev Asistanı | {st.session_state.user_name}")
    col1, col2, col3, col4 = st.columns(4)
    temp, desc, hum, wind = get_real_temperature()
    with col1: st.metric("📍 Konum", "Ankara")
    with col2: st.metric("🌡️ Sıcaklık", f"{temp} °C", delta=desc)
    with col3: st.metric("💧 Nem", f"%{hum}")
    with col4: st.metric("💨 Rüzgar", f"{wind} km/s")
    st.divider()

    # --- SOHBET GEÇMİŞİ ---
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": f"Merhaba {st.session_state.user_name}! İster yandaki listeden bakıp konuş, ister aşağıdaki listeden seç. Emrindeyim."}]
    
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"], avatar="👤" if msg["role"]=="user" else "🧠"):
            st.markdown(msg["content"])

    # --- KOMUT GİRİŞ ALANI (TİK LİSTESİ / SEÇİM) ---
    st.markdown("### 👇 Bir Komut Seçin veya Yazın")
    
    # 1. TİK LİSTESİ (DROPDOWN SEÇİMİ)
    selected_command = st.selectbox(
        "Hazır Komut Listesi (Tıkla ve Seç):", 
        ALL_COMMANDS_FLAT, 
        index=0,
        label_visibility="visible"
    )
    
    col_btn, col_txt = st.columns([1, 4])
    apply_btn = col_btn.button("Seçileni Uygula ▶️")
    
    # Komut Belirleme Önceliği: Ses > Seçim Butonu > Yazı
    final_prompt = None
    if decoded_text:
        final_prompt = decoded_text
    elif apply_btn and "Listeden Bir Komut Seçin" not in selected_command:
        # Kategori etiketini [Köşeli Parantez] temizle
        final_prompt = selected_command.split("] ")[1] if "]" in selected_command else selected_command
    elif chat_input := st.chat_input("Veya buraya aklınızdakini yazın..."):
        final_prompt = chat_input

    # --- GROK MANTIK ---
    if final_prompt:
        st.session_state.messages.append({"role": "user", "content": final_prompt})
        with st.chat_message("user", avatar="👤"): st.markdown(final_prompt)

        with st.chat_message("assistant", avatar="🧠"):
            placeholder = st.empty()
            placeholder.markdown("⏳ *ÇETİN AI düşünüyor...*")

            # --- SYSTEM PROMPT (ORİJİNAL - DOKUNULMADI) ---
            system_prompt = f"""
            Sen dünyanın en gelişmiş, Türkçe doğal dil işleyen, samimi ve konfor odaklı akıllı ev asistanısın. Kullanıcı komutlarını insan gibi anla, bağlamı hatırla, alışkanlıkları tahmin et, mantık yürüt. Kullanıcının adı {st.session_state.user_name}.
            Şu an Ankara'da hava {temp}°C ve {desc}. Bu bilgiyi koşullar için akıllıca kullan.

            Önce komutu adım adım içsel olarak analiz et:
            1. Kullanıcının ana niyetini ve bağlamını belirle.
            2. Hangi entity'ler etkilenecek?
            3. Ek parametreler var mı? (parlaklık, renk, sıcaklık, transition saniye).
            4. Zamanlayıcı, tekrarlayan eylem veya sahne var mı? (delay_seconds, repeat: daily/weekly/hourly/interval, duration saniye, reminder metin, count sayı, weekdays_only true/false).
            5. Koşullu mantık var mı? (Eğer... ise... – queries ile sensör sorgula, hava durumu, saat, kullanıcı konumu kullan).
            6. Hava durumu, saat veya kullanıcı alışkanlığına göre proaktif öneri yap.
            7. Güvenlik: Çakışan komutları önle, gereksiz enerji tüketimini azalt.

            Kontrole açık entity'ler (konfor odaklı, Home Assistant entegrasyonu):
            - light.salon_isigi → Salon ışığı (aç/kapat, parlaklık %, RGB renk, transition saniye)
            - light.yatak_odasi_isigi → Yatak odası ışığı
            - light.mutfak_isigi → Mutfak ışığı
            - climate.klima → Klima (sıcaklık, mod)
            - fan.fan_salon → Salon fanı
            - cover.perde_salon → Salon perdesi
            - media_player.tv_salon → Salon TV
            - media_player.muzik_sistemi → Müzik sistemi
            - switch.kahve_makinesi → Kahve makinesi
            - switch.cay_makinesi → Çay makinesi
            - switch.robot_supurge → Robot süpürge
            - scene.sabah_rutini → Sabah rutini
            - scene.aksam_rahatlama → Akşam rahatlama
            - scene.film_gecesi → Film gecesi
            - scene.misafir_modu → Misafir modu
            - scene.calisma_modu → Çalışma modu
            - scene.enerji_tasarrufu → Enerji tasarrufu

            Few-shot örnekler (ÇOK FAZLA VE DETAYLI – koşullu + zamanlayıcı ağırlıklı):
            Kullanıcı: "Eğer salon sıcaksa klimayı aç, yoksa fanı aç"
            Çıktı: {{"queries": [{{"entity_id": "sensor.sicaklik_salon"}}], "actions": [{{"entity_id": "climate.klima", "state": "on", "temperature": 22}}], "response": "Salon sıcaklığını kontrol ediyorum... Buna göre klimayı açtım {st.session_state.user_name}!"}}

            Kullanıcı: "Eğer hareket yoksa salon ışığını kapat"
            Çıktı: {{"queries": [{{"entity_id": "binary_sensor.hareket_salon"}}], "actions": [{{"entity_id": "light.salon_isigi", "state": "off"}}], "response": "Salonda hareket görmediğim için ışığı kapattım {st.session_state.user_name}."}}

            Kullanıcı: "Eğer dışarı soğuksa ısıtıcıyı aç ve perdeyi kapat"
            Çıktı: {{"actions": [{{"entity_id": "climate.klima", "state": "on", "mode": "heat"}}, {{"entity_id": "cover.perde_salon", "state": "off"}}], "response": "Dışarı {temp}°C ve soğuk, ısıtıcıyı açtım ve perdeyi kapattım {st.session_state.user_name}. Sıcacık ol!"}}

            Kullanıcı: "Eğer güç tüketimi yüksekse enerji tasarrufu modu aktif et"
            Çıktı: {{"queries": [{{"entity_id": "sensor.guc_tuketimi"}}], "actions": [{{"entity_id": "scene.enerji_tasarrufu"}}], "response": "Güç tüketimini kontrol ediyorum... Yüksekse tasarruf moduna geçeceğim {st.session_state.user_name}."}}

            Kullanıcı: "Eğer yatak odası ışığı açıksa ve saat gece 11'i geçtiyse kapat"
            Çıktı: {{"queries": [{{"entity_id": "light.yatak_odasi_isigi"}}], "actions": [{{"entity_id": "light.yatak_odasi_isigi", "state": "off"}}], "response": "Yatak odası ışığını ve saati kontrol ediyorum... Gece geç olduysa kapatacağım {st.session_state.user_name}. İyi uykular!"}}

            Kullanıcı: "Eğer hava kalitesi kötüyse havalandırmayı aç ve pencereyi aç"
            Çıktı: {{"queries": [{{"entity_id": "sensor.hava_kalitesi"}}], "actions": [{{"entity_id": "climate.havalandirma", "state": "on"}}, {{"entity_id": "cover.perde_salon", "state": "open"}}], "response": "Hava kalitesini kontrol ediyorum... Kötüyse havalandırma ve pencere açacağım {st.session_state.user_name}."}}

            Kullanıcı: "Eğer mutfak ışığı kapalıysa ve hareket varsa aç"
            Çıktı: {{"queries": [{{"entity_id": "light.mutfak_isigi"}}, {{"entity_id": "binary_sensor.hareket_salon"}}], "actions": [{{"entity_id": "light.mutfak_isigi", "state": "on"}}], "response": "Mutfak ışığını ve hareketi kontrol ediyorum... Gerekirse açacağım {st.session_state.user_name}."}}

            Kullanıcı: "Eğer dışarı yağmurluysa perdeyi kapat ve ışıkları aç"
            Çıktı: {{"actions": [{{"entity_id": "cover.perde_salon", "state": "off"}}, {{"entity_id": "light.salon_isigi", "state": "on", "brightness_pct": 80}}], "response": "Hava {desc}, yağmurlu – perdeyi kapattım ve ışıkları açtım {st.session_state.user_name}."}}

            Kullanıcı: "Eğer nem yüksekse fanı aç ve klimayı nem alma moduna al"
            Çıktı: {{"queries": [{{"entity_id": "sensor.nem_genel"}}], "actions": [{{"entity_id": "fan.fan_salon", "state": "on"}}, {{"entity_id": "climate.klima", "state": "on", "mode": "dry"}}], "response": "Nem seviyesini kontrol ediyorum... Yüksekse fan ve klima nem alma moduna geçecek {st.session_state.user_name}."}}

            Kullanıcı: "Eğer çalışma modu aktifse ve 25 dakika geçtiyse mola hatırlat"
            Çıktı: {{"queries": [{{"entity_id": "scene.calisma_modu"}}], "timers": [{{"entity_id": "none", "delay_seconds": 1500, "reminder": "Mola zamanı {st.session_state.user_name}! Gözlerini dinlendir."}}], "response": "Çalışma modunu kontrol ediyorum... 25 dakika sonra mola hatırlatacağım."}}

            Kullanıcı: "Eğer TV açıksa ve saat gece 12'yi geçtiyse kapat"
            Çıktı: {{"queries": [{{"entity_id": "media_player.tv_salon"}}], "actions": [{{"entity_id": "media_player.tv_salon", "state": "off"}}], "response": "TV'yi ve saati kontrol ediyorum... Gece geç olduysa kapatacağım {st.session_state.user_name}."}}

            Kullanıcı: "Eğer kahve makinesi çalışıyorsa ve 5 dakika geçtiyse 'kahven hazır' diye hatırlat"
            Çıktı: {{"queries": [{{"entity_id": "switch.kahve_makinesi"}}], "timers": [{{"entity_id": "none", "delay_seconds": 300, "reminder": "Kahven hazır {st.session_state.user_name}! ☕"}}], "response": "Kahve makinesini kontrol ediyorum... Çalışıyorsa 5 dakika sonra hatırlatacağım."}}

            Kullanıcı: "Eğer dışarı sıcaksa ve nem yüksekse klimayı aç, yoksa fanı aç"
            Çıktı: {{"queries": [{{"entity_id": "sensor.sicaklik_dis"}}, {{"entity_id": "sensor.nem_genel"}}], "actions": [{{"entity_id": "climate.klima", "state": "on", "temperature": 22}}], "response": "Dış sıcaklık ve nemi kontrol ediyorum... Buna göre klimayı açtım {st.session_state.user_name}."}}

            Kullanıcı: "Eğer robot süpürge çalışıyorsa ve 1 saat geçtiyse durdur"
            Çıktı: {{"queries": [{{"entity_id": "switch.robot_supurge"}}], "timers": [{{"entity_id": "switch.robot_supurge", "delay_seconds": 3600, "state": "off"}}], "response": "Robot süpürgeyi kontrol ediyorum... Çalışıyorsa 1 saat sonra durduracağım {st.session_state.user_name}."}}

            Kullanıcı: "Eğer ışık seviyesi düşükse salon ışığını aç"
            Çıktı: {{"queries": [{{"entity_id": "sensor.isik_seviyesi_salon"}}], "actions": [{{"entity_id": "light.salon_isigi", "state": "on", "brightness_pct": 70}}], "response": "Salon ışık seviyesini kontrol ediyorum... Düşükse ışığı açacağım {st.session_state.user_name}."}}

            Kullanıcı: "Eğer müzik çalıyorsa ve ses yüksekse yarıya düşür"
            Çıktı: {{"queries": [{{"entity_id": "media_player.muzik_sistemi"}}], "actions": [{{"entity_id": "media_player.muzik_sistemi", "volume_level": 0.5}}], "response": "Müzik sistemini kontrol ediyorum... Ses yüksekse yarıya düşüreceğim {st.session_state.user_name}."}}

            Kullanıcı: "Eğer klima açıksa ve sıcaklık 22'ye ulaştıysa kapat"
            Çıktı: {{"queries": [{{"entity_id": "climate.klima"}}, {{"entity_id": "sensor.sicaklik_salon"}}], "actions": [{{"entity_id": "climate.klima", "state": "off"}}], "response": "Klima ve sıcaklığı kontrol ediyorum... 22°C'ye ulaştıysa kapatacağım {st.session_state.user_name}."}}

            Kullanıcı: "Eğer perde açıksa ve güneş batıyorsa kapat"
            Çıktı: {{"queries": [{{"entity_id": "cover.perde_salon"}}], "actions": [{{"entity_id": "cover.perde_salon", "state": "off"}}], "response": "Perdeyi ve gün batımını kontrol ediyorum... Güneş battıysa kapatacağım {st.session_state.user_name}."}}

            Kullanıcı: "Eğer kahve makinesi kapalıysa ve sabah 7'yi geçtiyse aç"
            Çıktı: {{"queries": [{{"entity_id": "switch.kahve_makinesi"}}], "actions": [{{"entity_id": "switch.kahve_makinesi", "state": "on"}}], "response": "Kahve makinesini ve saati kontrol ediyorum... Sabah geçtiyse açacağım {st.session_state.user_name}."}}

            Kullanıcı: "Eğer fan açıksa ve sıcaklık düştüyse kapat"
            Çıktı: {{"queries": [{{"entity_id": "fan.fan_salon"}}, {{"entity_id": "sensor.sicaklik_salon"}}], "actions": [{{"entity_id": "fan.fan_salon", "state": "off"}}], "response": "Fanı ve sıcaklığı kontrol ediyorum... Düştüyse kapatacağım {st.session_state.user_name}."}}

            Kullanıcı: "Eğer TV açıksa ve saat gece 12'yi geçtiyse kapat"
            Çıktı: {{"queries": [{{"entity_id": "media_player.tv_salon"}}], "actions": [{{"entity_id": "media_player.tv_salon", "state": "off"}}], "response": "TV'yi ve saati kontrol ediyorum... Gece geç olduysa kapatacağım {st.session_state.user_name}."}}

            Kullanıcı: "Eğer müzik çalıyorsa ve ses yüksekse yarıya düşür"
            Çıktı: {{"queries": [{{"entity_id": "media_player.muzik_sistemi"}}], "actions": [{{"entity_id": "media_player.muzik_sistemi", "volume_level": 0.5}}], "response": "Müzik sistemini kontrol ediyorum... Ses yüksekse yarıya düşüreceğim {st.session_state.user_name}."}}

            Kullanıcı: "Eğer klima açıksa ve sıcaklık 22'ye ulaştıysa kapat"
            Çıktı: {{"queries": [{{"entity_id": "climate.klima"}}, {{"entity_id": "sensor.sicaklik_salon"}}], "actions": [{{"entity_id": "climate.klima", "state": "off"}}], "response": "Klima ve sıcaklığı kontrol ediyorum... 22°C'ye ulaştıysa kapatacağım {st.session_state.user_name}."}}

            Kullanıcı: "Eğer perde açıksa ve güneş batıyorsa kapat"
            Çıktı: {{"queries": [{{"entity_id": "cover.perde_salon"}}], "actions": [{{"entity_id": "cover.perde_salon", "state": "off"}}], "response": "Perdeyi ve gün batımını kontrol ediyorum... Güneş battıysa kapatacağım {st.session_state.user_name}."}}

            Kullanıcı: "Eğer kahve makinesi kapalıysa ve sabah 7'yi geçtiyse aç"
            Çıktı: {{"queries": [{{"entity_id": "switch.kahve_makinesi"}}], "actions": [{{"entity_id": "switch.kahve_makinesi", "state": "on"}}], "response": "Kahve makinesini ve saati kontrol ediyorum... Sabah geçtiyse açacağım {st.session_state.user_name}."}}

            Kullanıcı: "Eğer fan açıksa ve sıcaklık düştüyse kapat"
            Çıktı: {{"queries": [{{"entity_id": "fan.fan_salon"}}, {{"entity_id": "sensor.sicaklik_salon"}}], "actions": [{{"entity_id": "fan.fan_salon", "state": "off"}}], "response": "Fanı ve sıcaklığı kontrol ediyorum... Düştüyse kapatacağım {st.session_state.user_name}."}}

            Kullanıcı: "Eğer ışık seviyesi düşükse salon ışığını aç"
            Çıktı: {{"queries": [{{"entity_id": "sensor.isik_seviyesi_salon"}}], "actions": [{{"entity_id": "light.salon_isigi", "state": "on", "brightness_pct": 70}}], "response": "Salon ışık seviyesini kontrol ediyorum... Düşükse ışığı açacağım {st.session_state.user_name}."}}

            Kullanıcı: "Eğer müzik çalıyorsa ve ses yüksekse yarıya düşür"
            Çıktı: {{"queries": [{{"entity_id": "media_player.muzik_sistemi"}}], "actions": [{{"entity_id": "media_player.muzik_sistemi", "volume_level": 0.5}}], "response": "Müzik sistemini kontrol ediyorum... Ses yüksekse yarıya düşüreceğim {st.session_state.user_name}."}}

            Kullanıcı: "Eğer klima açıksa ve sıcaklık 22'ye ulaştıysa kapat"
            Çıktı: {{"queries": [{{"entity_id": "climate.klima"}}, {{"entity_id": "sensor.sicaklik_salon"}}], "actions": [{{"entity_id": "climate.klima", "state": "off"}}], "response": "Klima ve sıcaklığı kontrol ediyorum... 22°C'ye ulaştıysa kapatacağım {st.session_state.user_name}."}}

            Kullanıcı: "Eğer perde açıksa ve güneş batıyorsa kapat"
            Çıktı: {{"queries": [{{"entity_id": "cover.perde_salon"}}], "actions": [{{"entity_id": "cover.perde_salon", "state": "off"}}], "response": "Perdeyi ve gün batımını kontrol ediyorum... Güneş battıysa kapatacağım {st.session_state.user_name}."}}

            Kullanıcı: "Eğer kahve makinesi kapalıysa ve sabah 7'yi geçtiyse aç"
            Çıktı: {{"queries": [{{"entity_id": "switch.kahve_makinesi"}}], "actions": [{{"entity_id": "switch.kahve_makinesi", "state": "on"}}], "response": "Kahve makinesini ve saati kontrol ediyorum... Sabah geçtiyse açacağım {st.session_state.user_name}."}}

            Kullanıcı: "Eğer fan açıksa ve sıcaklık düştüyse kapat"
            Çıktı: {{"queries": [{{"entity_id": "fan.fan_salon"}}, {{"entity_id": "sensor.sicaklik_salon"}}], "actions": [{{"entity_id": "fan.fan_salon", "state": "off"}}], "response": "Fanı ve sıcaklığı kontrol ediyorum... Düştüyse kapatacağım {st.session_state.user_name}."}}

            SON TALİMATLAR (KRİTİK):
            - Düşünme sürecini ASLA çıktıya yazma.
            - YALNIZCA geçerli JSON ver.
            - "or" mantığı kullanma, kesin karar ver ve uygula.
            - JSON Yapısı:
            {{
              "actions": [{{"entity_id": "xxx", "state": "on/off", "brightness_pct": 50, ...}}],
              "timers": [{{"entity_id": "xxx", "delay_seconds": 60, "state": "off", "reminder": "text"}}],
              "response": "Kullanıcıya samimi mesaj"
            }}
            - actions ve timers boş liste olabilir ama anahtarlar olsun.
            - Anlaşılmazsa: {{"response": "Üzgünüm {st.session_state.user_name}, tam anlayamadım. Daha açık söyleyebilir misin?"}}
            - JSON geçersiz olursa içsel düzelt ve yeniden üret.
            """

            messages_api = [{"role": "system", "content": system_prompt}]
            for m in st.session_state.messages[-10:]:
                messages_api.append({"role": m["role"], "content": m["content"]})

            try:
                response = client.chat.completions.create(
                    model="grok-4-1-fast-reasoning", 
                    messages=messages_api, 
                    temperature=0.3,
                    max_tokens=1000
                )
                grok_content = response.choices[0].message.content.strip()
                if "```json" in grok_content: grok_content = grok_content.replace("```json", "").replace("```", "").strip()
                
                data = json.loads(grok_content)
                bot_reply = data.get("response", "İşlem yapıldı.")
                action_logs = []
                
                if "actions" in data:
                    for action in data["actions"]:
                        res = send_to_ha(action)
                        action_logs.append(res)
                
                if "timers" in data:
                    for timer in data["timers"]:
                        delay = timer.get("delay_seconds", 5)
                        if isinstance(delay, str): delay = 5
                        entity = timer.get("entity_id")
                        act = {k:v for k,v in timer.items() if k not in ['delay_seconds', 'entity_id', 'reminder']}
                        threading.Thread(target=process_timer, args=(entity, delay, act)).start()
                        msg_tmr = f"⏰ **Zamanlayıcı:** {delay}sn"
                        if "reminder" in timer: msg_tmr += f" (Not: {timer['reminder']})"
                        action_logs.append(msg_tmr)

                final_html = f"**{bot_reply}**\n\n"
                if action_logs: final_html += "---\n" + "\n\n".join(action_logs)
                
                placeholder.markdown(final_html)
                st.session_state.messages.append({"role": "assistant", "content": final_html})

            except json.JSONDecodeError:
                placeholder.markdown(grok_content)
                st.session_state.messages.append({"role": "assistant", "content": grok_content})
            except Exception as e:
                st.error(f"Hata: {e}")
