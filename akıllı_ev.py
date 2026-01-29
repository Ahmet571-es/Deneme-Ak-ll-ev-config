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

# --- 1. SAYFA AYARLARI (GÖRÜNÜM) ---
st.set_page_config(
    page_title="Grok Ev Asistanı", 
    page_icon="🧠", 
    layout="wide", 
    initial_sidebar_state="expanded"
)

# --- 2. ÖZEL CSS (PROFESYONEL TASARIM) ---
st.markdown("""
<style>
    /* Ana başlık rengi */
    h1 {
        color: #FF4B4B;
        font-family: 'Helvetica Neue', sans-serif;
    }
    /* Metrik kutularının arka planı */
    div[data-testid="stMetric"] {
        background-color: #262730;
        border: 1px solid #464b5f;
        padding: 15px;
        border-radius: 10px;
        color: white;
    }
    /* Sohbet baloncukları */
    .stChatMessage {
        border-radius: 15px;
        padding: 10px;
    }
</style>
""", unsafe_allow_html=True)

# --- AYARLAR ---
load_dotenv()
GROK_API_KEY = os.getenv("GROK_API_KEY")
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY")
HA_URL = os.getenv("HA_URL")
HA_TOKEN = os.getenv("HA_TOKEN")

if not GROK_API_KEY:
    st.error("⚠️ GROK_API_KEY eksik! .env dosyasını kontrol et.")
    st.stop()

# Grok client
client = openai.OpenAI(api_key=GROK_API_KEY, base_url="https://api.x.ai/v1")

# --- ENTITY TANIMLARI ---
ENTITY_NAMES = {
    "light.salon_isigi": "Salon Işığı",
    "light.yatak_odasi_isigi": "Yatak Odası Işığı",
    "light.mutfak_isigi": "Mutfak Işığı",
    "climate.klima": "Klima",
    "fan.fan_salon": "Salon Fanı",
    "cover.perde_salon": "Salon Perdesi",
    "media_player.tv_salon": "Salon TV",
    "media_player.muzik_sistemi": "Müzik Sistemi",
    "switch.kahve_makinesi": "Kahve Makinesi",
    "switch.cay_makinesi": "Çay Makinesi",
    "switch.robot_supurge": "Robot Süpürge",
    "scene.sabah_rutini": "Sabah Rutini",
    "scene.aksam_rahatlama": "Akşam Rahatlama",
    "scene.film_gecesi": "Film Gecesi",
    "scene.misafir_modu": "Misafir Modu",
    "scene.calisma_modu": "Çalışma Modu",
    "scene.enerji_tasarrufu": "Enerji Tasarrufu"
}

# --- FONKSİYONLAR ---

# 1. Gerçek Hava Durumu (Dashboard için Nem ve Rüzgar eklendi)
def get_real_temperature():
    if OPENWEATHER_API_KEY:
        try:
            url = f"http://api.openweathermap.org/data/2.5/weather?q=Ankara&appid={OPENWEATHER_API_KEY}&units=metric&lang=tr"
            response = requests.get(url, timeout=3).json()
            if response.get("main"):
                temp = response['main']['temp']
                desc = response['weather'][0]['description']
                hum = response['main'].get('humidity', 50) # Nem
                wind = response['wind'].get('speed', 10)   # Rüzgar
                return temp, desc, hum, wind
        except:
            pass
    return 22.0, "parçalı bulutlu (simülasyon)", 45, 12

# 2. ÜCRETSİZ Ses Tanıma
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

# 3. Home Assistant (Simülasyon veya Gerçek - Görsel İkonlar Eklendi)
def send_to_ha(action):
    entity_id = action.get("entity_id")
    if not entity_id: return "Hata: Cihaz ID yok"
    
    device_name = ENTITY_NAMES.get(entity_id, entity_id)

    # Gerçek HA varsa oraya gönder
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
            
    # SİMÜLASYON Cevabı
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

# Kullanıcı Adı Yönetimi (Şık Form)
if "user_name" not in st.session_state:
    st.session_state.user_name = ""

if not st.session_state.user_name:
    with st.form("name_form"):
        st.subheader("👋 Hoş Geldiniz")
        st.write("Sistemi başlatmak için adınızı girin.")
        name_input = st.text_input("Adınız")
        if st.form_submit_button("Sistemi Başlat 🚀") and name_input.strip():
            st.session_state.user_name = name_input.strip().split()[0]
            st.rerun()
else:
    user_name = st.session_state.user_name

# --- ARAYÜZ YERLEŞİMİ (DASHBOARD) ---
# Üst Kısım: Hava Durumu Kartları
col1, col2, col3, col4 = st.columns(4)
temp, desc, hum, wind = get_real_temperature()

with col1:
    st.metric(label="📍 Konum", value="Ankara")
with col2:
    st.metric(label="🌡️ Sıcaklık", value=f"{temp} °C", delta=desc)
with col3:
    st.metric(label="💧 Nem", value=f"%{hum}")
with col4:
    st.metric(label="💨 Rüzgar", value=f"{wind} km/s")

st.divider()

# Yan Panel: Ses Kaydedici
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/4712/4712035.png", width=80)
    st.title("Kontrol Paneli")
    st.markdown("---")
    st.write("🎙️ **Sesli Komut**")
    
    audio = mic_recorder(start_prompt="🔴 Kaydı Başlat", stop_prompt="⏹ Bitir", key="recorder")
    
    decoded_text = None
    if audio:
        with st.spinner("Ses işleniyor..."):
            decoded_text = transcribe_audio_free(audio["bytes"])
        if decoded_text:
            st.success(f"Algılanan: '{decoded_text}'")
        else:
            st.warning("Ses anlaşılamadı.")
    
    st.markdown("---")
    st.info("💡 İpucu: 'Sabah modunu aç' veya '30dk sonra ışığı kapat' diyebilirsiniz.")

# Sohbet Geçmişi
if "messages" not in st.session_state:
    st.session_state.messages = [{"role": "assistant", "content": f"Merhaba {user_name}! Evin kontrolü bende. Ne yapmak istersin?"}]

for msg in st.session_state.messages:
    if msg["role"] == "user":
        with st.chat_message("user", avatar="👤"):
            st.markdown(msg["content"])
    else:
        with st.chat_message("assistant", avatar="🧠"):
            st.markdown(msg["content"])

# Komut Girişi
prompt = None
if decoded_text:
    prompt = decoded_text
elif chat_input := st.chat_input("Komutunuzu yazın..."):
    prompt = chat_input

# --- ANA MANTIK ---
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user", avatar="👤"):
        st.markdown(prompt)

    with st.chat_message("assistant", avatar="🧠"):
        placeholder = st.empty()
        placeholder.markdown("⏳ *Grok düşünüyor...*")

        # --- SYSTEM PROMPT (DOKUNULMADI - TAM OLARAK İSTEDİĞİN GİBİ) ---
        system_prompt = f"""
        Sen dünyanın en gelişmiş, Türkçe doğal dil işleyen, samimi ve konfor odaklı akıllı ev asistanısın. Kullanıcı komutlarını insan gibi anla, bağlamı hatırla, alışkanlıkları tahmin et. Kullanıcının adı {user_name}.
        Şu an Ankara'da hava {temp}°C ve {desc}.

        Kontrole açık entity'ler (konfor odaklı):
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

        Few-shot örnekler (İLERİ SEVİYE ZAMANLAYICI ÖRNEKLERİ ÇOK DAHA FAZLA EKLENDİ):
        Kullanıcı: "Sabah rutini başlat"
        Çıktı: {{"actions": [{{"entity_id": "scene.sabah_rutini"}}], "response": "Günaydın {user_name}! Sabah rutini aktif."}}

        Kullanıcı: "30 dakika sonra salon ışığını kapat"
        Çıktı: {{"timers": [{{"entity_id": "light.salon_isigi", "delay_seconds": 1800, "state": "off"}}], "response": "Tamam {user_name}, 30 dakika sonra salon ışığını kapatacağım."}}

        Kullanıcı: "Her sabah 7'de kahve hazırla ve ışıkları yavaş aç"
        Çıktı: {{"timers": [{{"entity_id": "script.kahve_hazirla", "delay_seconds": "sabah7_hesapla", "repeat": "daily"}}, {{"entity_id": "light.salon_isigi", "state": "on", "transition": 300, "repeat": "daily"}}], "response": "Her sabah 7'de kahve ve ışık rutini ayarlandı {user_name}!"}}

        Kullanıcı: "Eğer dışarı sıcaksa 1 saat sonra fanı aç, soğuksa ısıtıcıyı aç"
        Çıktı: {{"timers": [{{"entity_id": "fan.fan_salon", "delay_seconds": 3600, "state": "on"}}], "response": "Hava durumuna göre 1 saat sonra fan açılacak {user_name}."}}

        Kullanıcı: "Akşam 8'den sonra 2 saat boyunca her 30 dakikada bir hatırlatma yap: Su iç"
        Çıktı: {{"timers": [{{"entity_id": "none", "delay_seconds": 1800, "repeat": "interval", "reminder": "Su içme zamanı {user_name}!"}}], "response": "Akşam 8'den itibaren her 30 dakikada su iç hatırlatması yapacağım."}}

        Kullanıcı: "Hafta sonu sabah 9'da robot süpürgeyi başlat ve müzik aç"
        Çıktı: {{"timers": [{{"entity_id": "switch.robot_supurge", "delay_seconds": "haftasonu9_hesapla", "repeat": "weekly"}}, {{"entity_id": "media_player.muzik_sistemi", "state": "on", "repeat": "weekly"}}], "response": "Hafta sonu sabah 9 rutin ayarlandı {user_name}."}}

        Kullanıcı: "Film gecesi modu ve 2 saat sonra ışıkları otomatik kapat"
        Çıktı: {{"actions": [{{"entity_id": "scene.film_gecesi"}}], "timers": [{{"entity_id": "light.salon_isigi", "delay_seconds": 7200, "state": "off"}}], "response": "Film gecesi aktif, 2 saat sonra ışıklar kapanacak {user_name}."}}

        Kullanıcı: "Her akşam 10'da yatak odası ışığını loş yap ve klimayı 22 dereceye ayarla"
        Çıktı: {{"timers": [{{"entity_id": "light.yatak_odasi_isigi", "state": "on", "brightness_pct": 30, "repeat": "daily"}}, {{"entity_id": "climate.klima", "temperature": 22, "repeat": "daily"}}], "response": "Her akşam 10 uyku rutini ayarlandı {user_name}, iyi geceler!"}}

        Kullanıcı: "Eğer hava sıcaksa her saat başı fanı 10 dakika aç"
        Çıktı: {{"timers": [{{"entity_id": "fan.fan_salon", "delay_seconds": 600, "state": "on", "repeat": "hourly", "duration": 600}}], "response": "Sıcak havalarda her saat fan 10 dakika çalışacak {user_name}."}}

        SON TALİMATLAR: YALNIZCA geçerli JSON ver. Yorum yapma.
        """

        messages_api = [{"role": "system", "content": system_prompt}]
        for m in st.session_state.messages[-10:]:
            messages_api.append({"role": m["role"], "content": m["content"]})

        try:
            # Grok API Çağrısı (Model Korundu: grok-4-1-fast-reasoning)
            response = client.chat.completions.create(
                model="grok-4-1-fast-reasoning", 
                messages=messages_api, 
                temperature=0.3,
                max_tokens=1000
            )
            grok_content = response.choices[0].message.content.strip()
            
            if "```json" in grok_content:
                grok_content = grok_content.replace("```json", "").replace("```", "").strip()
            
            try:
                data = json.loads(grok_content)
                bot_reply = data.get("response", "İşlem yapıldı.")
                
                action_logs = []
                if "actions" in data:
                    for action in data["actions"]:
                        res = send_to_ha(action)
                        action_logs.append(res)
                
                if "timers" in data:
                    for timer in data["timers"]:
                        delay = timer.get("delay_seconds", 0)
                        if isinstance(delay, str): delay = 5 
                        entity = timer.get("entity_id")
                        act = {k:v for k,v in timer.items() if k not in ['delay_seconds', 'entity_id', 'repeat', 'duration']}
                        threading.Thread(target=process_timer, args=(entity, delay, act)).start()
                        
                        tekrar = f" (Tekrar: {timer.get('repeat')})" if "repeat" in timer else ""
                        action_logs.append(f"⏰ **Zamanlayıcı:** {ENTITY_NAMES.get(entity, entity)} ({delay}sn) {tekrar}")

                # Final Gösterim (Daha Şık)
                final_html = f"**{bot_reply}**\n\n"
                if action_logs:
                    final_html += "---\n" + "\n\n".join(action_logs)
                
                placeholder.markdown(final_html)
                st.session_state.messages.append({"role": "assistant", "content": final_html})

            except json.JSONDecodeError:
                placeholder.markdown(grok_content)
                st.session_state.messages.append({"role": "assistant", "content": grok_content})

        except Exception as e:
            st.error(f"API Hatası: {e}")
