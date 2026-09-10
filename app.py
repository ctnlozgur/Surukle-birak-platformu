Python
import streamlit as st
import pandas as pd
import re
import plotly.express as px
import streamlit as st
import pandas as pd
import datetime
import re

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="Akıllı Biletleme & Dinamik Fiyat Dashboard", layout="wide", page_icon="🎫")

st.title("🎫 Akıllı Biletleme & Dinamik Fiyatlandırma Merkezi")
st.markdown("Etkinlik raporunuzu (Örn: Erdal Erzincan Konseri) aşağıya sürükleyin. Sistem isim karmaşasını çözecek ve doluluk oranına göre fiyat simülasyonu yapacaktır.")

# --- DOSYA YÜKLEME ---
uploaded_file = st.file_uploader("Excel Raporunu Yükleyin (.xlsx)", type=["xlsx"])

if uploaded_file is not None:
    with st.spinner('Veriler analiz ediliyor ve kategorize ediliyor...'):
        # Veriyi 7. satırdan (header=6) itibaren oku
        df = pd.read_excel(uploaded_file, header=6)
        
        # Sadece ilgili sütunları al ve boş/gereksiz satırları temizle
        df = df.iloc[:, 0:6].dropna(subset=['Koltuk Grubu', 'Fiyat'])
        df = df[~df['Koltuk Grubu'].str.contains("TOPLAM|Fiyat Bazında", na=False, case=False)]
        
        # Veri tiplerini düzelt
        for col in ['Fiyat', 'İnd. Fiyat', 'Stok', 'Kalan Stok']:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

        # Satılan bilet sayısını hesapla
        df['Satılan'] = df['Stok'] - df['Kalan Stok']

        # --- AKILLI KATEGORİZASYON FONKSİYONU ---
        def categorize(name):
            name_clean = str(name).replace('İ', 'i').replace('I', 'ı').lower()
            
            # Ana Kategori
            kat_match = re.search(r'(\d+)\.\s*kategori', name_clean)
            if kat_match:
                kat = f"{kat_match.group(1)}. Kategori"
            elif "sahne önü" in name_clean or "sahne onu" in name_clean: kat = "Sahne Önü"
            elif "protokol" in name_clean: kat = "Protokol"
            elif "gold" in name_clean: kat = "Gold"
            elif "silver" in name_clean: kat = "Silver"
            elif "vip" in name_clean: kat = "VIP"
            else: kat = "Diğer"
                
            # Bilet Tipi
            if "çift kişilik" in name_clean or "cift kisilik" in name_clean: tip = "Çift Kişilik"
            elif "indirim" in name_clean or "fırsat" in name_clean: tip = "İndirimli"
            elif "öğrenci" in name_clean: tip = "Öğrenci"
            else: tip = "Standart"
                
            return pd.Series([kat, tip])

        df[['Ana Kategori', 'Bilet Tipi']] = df['Koltuk Grubu'].apply(categorize)

        # --- DİNAMİK FİYATLANDIRMA ALGORİTMASI ---
        def dinamik_fiyat_hesapla(row):
            if row['Stok'] == 0: return row['Fiyat'], "Aksiyon Yok"
            
            doluluk = row['Satılan'] / row['Stok']
            mevcut_fiyat = row['Fiyat']
            
            # Simülasyon Kuralları (Stok erime hızına göre)
            if doluluk >= 0.85 and row['Kalan Stok'] > 0:
                return mevcut_fiyat * 1.15, "🚀 %15 Fiyat Artır (Yüksek Talep)"
            elif doluluk >= 0.65 and row['Kalan Stok'] > 0:
                return mevcut_fiyat * 1.05, "📈 %5 Fiyat Artır (İyi İvme)"
            elif doluluk <= 0.20 and row['Satılan'] > 0: # Hiç satılmadıysa bekletilebilir
                return mevcut_fiyat * 0.90, "📉 %10 İndirim Yap (Düşük Talep)"
            elif row['Kalan Stok'] == 0:
                return mevcut_fiyat, "Tükendi (Sold Out)"
            else:
                return mevcut_fiyat, "Bekle (Optimum Seyir)"

        df[['Önerilen Fiyat', 'Aksiyon Önerisi']] = df.apply(dinamik_fiyat_hesapla, axis=1, result_type="expand")
        
        # Toplam Ciro Hesaplama
        df['Mevcut Ciro'] = df['Satılan'] * df['İnd. Fiyat']

        # --- DASHBOARD ARAYÜZÜ ---
        
        # 1. Özet Metrikler
        st.markdown("### 📊 Genel Etkinlik Özeti")
        toplam_stok = int(df['Stok'].sum())
        toplam_satilan = int(df['Satılan'].sum())
        genel_doluluk = (toplam_satilan / toplam_stok) * 100 if toplam_stok > 0 else 0
        toplam_ciro = df['Mevcut Ciro'].sum()

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Toplam Kapasite", f"{toplam_stok}")
        col2.metric("Satılan Bilet", f"{toplam_satilan}")
        col3.metric("Genel Doluluk", f"%{genel_doluluk:.1f}")
        col4.metric("Tahmini Mevcut Ciro", f"₺{toplam_ciro:,.0f}")

        st.divider()

        # 2. Ana Tablo ve Aksiyonlar
        st.markdown("### 🧠 Kategori Bazlı Dinamik Fiyatlandırma Aksiyonları")
        
        # Sadece analiz için gerekli sütunları göster
        display_df = df[['Ana Kategori', 'Bilet Tipi', 'Stok', 'Kalan Stok', 'Satılan', 'Fiyat', 'Önerilen Fiyat', 'Aksiyon Önerisi']]
        
        # Kategoriye göre gruplayıp gösterme
        grouped_df = display_df.groupby(['Ana Kategori', 'Bilet Tipi']).agg({
            'Stok': 'sum',
            'Satılan': 'sum',
            'Kalan Stok': 'sum',
            'Fiyat': 'mean'
        }).reset_index()
        
        # Gruplanmış veri üzerinden tekrar dinamik fiyat önerisi hesapla
        grouped_df[['Önerilen Fiyat', 'Aksiyon Önerisi']] = grouped_df.apply(dinamik_fiyat_hesapla, axis=1, result_type="expand")
        
        # Tabloyu formatlayıp ekrana bas
        st.dataframe(grouped_df.style.format({
            "Fiyat": "₺{:.0f}",
            "Önerilen Fiyat": "₺{:.0f}"
        }), use_container_width=True)

        st.divider()

        # 3. Görselleştirme
        st.markdown("### 📈 Kategori Bazlı Satış Performansı")
        fig = px.bar(grouped_df, x="Ana Kategori", y=["Satılan", "Kalan Stok"], 
                     color="Bilet Tipi", barmode="stack",
                     title="Hangi Kategori Ne Kadar Sattı?",
                     labels={"value": "Bilet Adedi", "variable": "Durum"})
        st.plotly_chart(fig, use_container_width=True)

else:
    st.info("Lütfen analize başlamak için sol üstten veya yukarıdaki alandan Excel dosyanızı yükleyin.")
