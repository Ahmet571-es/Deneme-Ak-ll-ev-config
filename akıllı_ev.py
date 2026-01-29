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

# --- 2. ÖZEL TASARIM (CSS) ---
st.markdown("""
<style>
    /* Ana başlık stili */
    h1 {
        color: #FF4B4B;
        font-family: 'Helvetica Neue', sans-serif;
        text-align: center;
    }
    /* Metrik kutuları */
    div[data-testid="stMetric"] {
        background-color: #262730;
        border: 1px solid #464b5f;
        padding: 15px;
        border-radius: 10px;
        color: white;
    }
    /* Butonlar */
    div.stButton > button {
        width: 100%;
        border-radius: 10px;
        height: 50px;
        font-weight: bold;
    }
    /* Sohbet baloncukları */
    .stChatMessage {
        border-radius: 15px;
        padding: 10px;
    }
    /* Expander Başlığı */
    .streamlit-expanderHeader {
        font-size: 18px;
        font-weight: bold;
        color: #FF4B4B;
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
    st.error("⚠️ GROK_API_KEY eksik! Streamlit Secrets ayarlarını kontrol et.")
    st.stop()

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

# --- UYGULAMA AKIŞ KONTROLÜ ---
if "page" not in st.session_state:
    st.session_state.page = "welcome"
if "user_name" not in st.session_state:
    st.session_state.user_name = ""

# --- SAYFA 1: KARŞILAMA VE BİLGİ ---
if st.session_state.page == "welcome":
    st.title("🏠 ÇETİN AI Ev Asistanı")
    st.markdown("---")
    
    # Detaylı Bilgi Butonu (Expander)
    with st.expander("ℹ️ Bu Uygulama Nedir ve Nasıl Kullanılır? (Okumak için Tıklayın)", expanded=False):
        st.markdown("""
        ### 📱 Uygulama Ne İşe Yarar?
        ÇETİN AI, klasik akıllı ev sistemlerinin aksine, sizinle **konuşarak anlaşan** ve **düşünebilen** yeni nesil bir ev asistanıdır. Sadece düğmelere basmak yerine, ona derdinizi anlatırsınız, o da ne yapması gerektiğine karar verir.

        ### 🎯 Uygulamanın Amacı Nedir?
        Bu projenin temel amacı, karmaşık ev otomasyon sistemlerini herkesin (çocuklardan yaşlılara kadar) kullanabileceği kadar **basit ve doğal** hale getirmektir. Yapay zeka gücüyle, evinizdeki cihazları yönetmek için mühendis olmanıza gerek kalmaz.

        ### 🛠️ Uygulama İle Neler Yapabilirsiniz?
        Bu asistan ile evinizdeki şu cihazları yönetebilirsiniz:
        * **Aydınlatma:** Işıkları açabilir, kapatabilir veya parlaklığını ayarlayabilirsiniz.
        * **İklimlendirme:** Kombiyi veya klimayı ortam sıcaklığına göre kontrol edebilirsiniz.
        * **Güvenlik ve Konfor:** Perdeleri açıp kapatabilir, kapı kilitlerini kontrol edebilirsiniz.
        * **Ev Aletleri:** Robot süpürgeyi çalıştırabilir, kahve makinesini açabilirsiniz.
        * **Senaryolar:** "Film Modu", "Sabah Rutini" gibi tek komutla evi baştan aşağı değiştiren modları kullanabilirsiniz.

        ### 🚀 Uygulama Nasıl Kullanılır? (Adım Adım)
        1.  **Başlatın:** Aşağıdaki 'Uygulamayı Başlatın' butonuna basın.
        2.  **Tanışın:** Adınızı girin ki asistan size isminizle hitap edebilsin.
        3.  **Emir Verin:**
            * **Sesli:** Mikrofon butonuna basıp "Işıkları yak" diyebilirsiniz.
            * **Yazılı:** Sohbet kutusuna "Hava soğuksa kombiyi aç" yazabilirsiniz.
        4.  **Sonucu Görün:** Asistanın işlemi yaptığını ekranda anlık olarak göreceksiniz.
        """)
    
    st.write("") # Boşluk
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
        # value="" diyerek her seferinde boş gelmesini sağlıyoruz
        name_input = st.text_input("Adınız:", value="", placeholder="Örn: Ahmet Bey")
        
        submitted = st.form_submit_button("Sisteme Giriş Yap ✅")
        if submitted and name_input.strip():
            st.session_state.user_name = name_input.strip().split()[0]
            st.session_state.page = "main_app"
            st.rerun()
        elif submitted:
            st.warning("Lütfen geçerli bir isim giriniz.")

# --- SAYFA 3: ANA UYGULAMA (DASHBOARD) ---
elif st.session_state.page == "main_app":
    # --- YAN PANEL (SIDEBAR) ---
    with st.sidebar:
        st.image("https://cdn-icons-png.flaticon.com/512/4712/4712035.png", width=80)
        st.title("ÇETİN AI Panel")
        st.markdown("---")
        
        st.write("🎙️ **Sesli Komut**")
        audio = mic_recorder(start_prompt="🔴 Kaydı Başlat", stop_prompt="⏹ Bitir", key="recorder")
        
        decoded_text = None
        if audio:
            with st.spinner("Sesiniz yazıya çevriliyor..."):
                decoded_text = transcribe_audio_free(audio["bytes"])
            if decoded_text:
                st.success(f"Algılanan: '{decoded_text}'")
            else:
                st.warning("Ses anlaşılamadı.")
        
        st.markdown("---")
        st.info("💡 **İpucu:** 'Hava durumu nasıl?' veya 'Misafir modu başlat' diyebilirsiniz.")
        
        st.markdown("---")
        # ÇIKIŞ BUTONU
        if st.button("🚪 Uygulamadan Ayrıl"):
            st.session_state.page = "welcome"
            st.session_state.user_name = ""
            st.session_state.messages = [] # Geçmişi temizle
            st.rerun()

    # --- ANA EKRAN İÇERİĞİ ---
    st.title(f"🏠 ÇETİN AI Ev Asistanı | {st.session_state.user_name}")
    
    # Hava Durumu Kartları
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

    # Sohbet Geçmişi Başlatma
    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": f"Merhaba {st.session_state.user_name}! Evin kontrolü bende. Nasıl yardımcı olabilirim?"}]

    # Mesajları Ekrana Yazdır
    for msg in st.session_state.messages:
        if msg["role"] == "user":
            with st.chat_message("user", avatar="👤"):
                st.markdown(msg["content"])
        else:
            with st.chat_message("assistant", avatar="🧠"):
                st.markdown(msg["content"])

    # Komut Girişi (Ses veya Yazı)
    prompt = None
    if decoded_text:
        prompt = decoded_text
    elif chat_input := st.chat_input("Bir komut yazın (Örn: Işıkları kapat)..."):
        prompt = chat_input

    # --- GROK MANTIK ---
    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user", avatar="👤"):
            st.markdown(prompt)

        with st.chat_message("assistant", avatar="🧠"):
            placeholder = st.empty()
            placeholder.markdown("⏳ *ÇETİN AI düşünüyor...*")

            # --- SYSTEM PROMPT (DOKUNULMADI) ---
            system_prompt = f"""
            Sen dünyanın en gelişmiş, Türkçe doğal dil işleyen, samimi ve konfor odaklı akıllı ev asistanısın. Kullanıcı komutlarını insan gibi anla, bağlamı hatırla, alışkanlıkları tahmin et. Kullanıcının adı {st.session_state.user_name}.
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
            Çıktı: {{"actions": [{{"entity_id": "scene.sabah_rutini"}}], "response": "Günaydın {st.session_state.user_name}! Sabah rutini aktif."}}

            Kullanıcı: "30 dakika sonra salon ışığını kapat"
            Çıktı: {{"timers": [{{"entity_id": "light.salon_isigi", "delay_seconds": 1800, "state": "off"}}], "response": "Tamam {st.session_state.user_name}, 30 dakika sonra salon ışığını kapatacağım."}}

            Kullanıcı: "Her sabah 7'de kahve hazırla ve ışıkları yavaş aç"
            Çıktı: {{"timers": [{{"entity_id": "script.kahve_hazirla", "delay_seconds": "sabah7_hesapla", "repeat": "daily"}}, {{"entity_id": "light.salon_isigi", "state": "on", "transition": 300, "repeat": "daily"}}], "response": "Her sabah 7'de kahve ve ışık rutini ayarlandı {st.session_state.user_name}!"}}

            Kullanıcı: "Eğer dışarı sıcaksa 1 saat sonra fanı aç, soğuksa ısıtıcıyı aç"
            Çıktı: {{"timers": [{{"entity_id": "fan.fan_salon", "delay_seconds": 3600, "state": "on"}}], "response": "Hava durumuna göre 1 saat sonra fan açılacak {st.session_state.user_name}."}}

            Kullanıcı: "Akşam 8'den sonra 2 saat boyunca her 30 dakikada bir hatırlatma yap: Su iç"
            Çıktı: {{"timers": [{{"entity_id": "none", "delay_seconds": 1800, "repeat": "interval", "reminder": "Su içme zamanı {st.session_state.user_name}!"}}], "response": "Akşam 8'den itibaren her 30 dakikada su iç hatırlatması yapacağım."}}

            Kullanıcı: "Hafta sonu sabah 9'da robot süpürgeyi başlat ve müzik aç"
            Çıktı: {{"timers": [{{"entity_id": "switch.robot_supurge", "delay_seconds": "haftasonu9_hesapla", "repeat": "weekly"}}, {{"entity_id": "media_player.muzik_sistemi", "state": "on", "repeat": "weekly"}}], "response": "Hafta sonu sabah 9 rutin ayarlandı {st.session_state.user_name}."}}

            Kullanıcı: "Film gecesi modu ve 2 saat sonra ışıkları otomatik kapat"
            Çıktı: {{"actions": [{{"entity_id": "scene.film_gecesi"}}], "timers": [{{"entity_id": "light.salon_isigi", "delay_seconds": 7200, "state": "off"}}], "response": "Film gecesi aktif, 2 saat sonra ışıklar kapanacak {st.session_state.user_name}."}}

            Kullanıcı: "Her akşam 10'da yatak odası ışığını loş yap ve klimayı 22 dereceye ayarla"
            Çıktı: {{"timers": [{{"entity_id": "light.yatak_odasi_isigi", "state": "on", "brightness_pct": 30, "repeat": "daily"}}, {{"entity_id": "climate.klima", "temperature": 22, "repeat": "daily"}}], "response": "Her akşam 10 uyku rutini ayarlandı {st.session_state.user_name}, iyi geceler!"}}

            Kullanıcı: "Eğer hava sıcaksa her saat başı fanı 10 dakika aç"
            Çıktı: {{"timers": [{{"entity_id": "fan.fan_salon", "delay_seconds": 600, "state": "on", "repeat": "hourly", "duration": 600}}], "response": "Sıcak havalarda her saat fan 10 dakika çalışacak {st.session_state.user_name}."}}

            SON TALİMATLAR: YALNIZCA geçerli JSON ver. Yorum yapma.
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
