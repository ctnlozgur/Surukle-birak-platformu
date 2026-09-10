import streamlit as st
import pandas as pd
import re
import plotly.express as px

# --- SAYFA AYARLARI VE BAŞLIK ---
st.set_page_config(page_title="V4.0 Dinamik Biletleme & Fiyat Botu", layout="wide", page_icon="🎫")

st.title("🎫 V4.0 Dinamik Biletleme ve Fiyatlandırma Botu")
st.markdown("Etkinlik satış raporunu aşağıya sürükleyin. V4.0 algoritması analiz yapar, yeni fiyatı manuel değiştirdiğinizde toplam ciro hedefleri anında güncellenir.")

# --- KULLANICI GİRDİLERİ (YAN MENÜ) ---
with st.sidebar:
    st.header("⚙️ Etkinlik Ayarları")
    hedef_doluluk = st.slider("Hedef Doluluk Oranı (%)", min_value=50, max_value=100, value=85) / 100
    st.info("Algoritma, bu hedef doluluğa ve biletlerin erime hızına göre fiyat önerileri sunar.")

# --- DOSYA YÜKLEME ALANI ---
uploaded_file = st.file_uploader("Bilet Satış Raporunu Yükleyin (.xlsx)", type=["xlsx"])

if uploaded_file is not None:
    with st.spinner('Rapor işleniyor, V4.0 bot kararları hesaplanıyor...'):
        # 1. VERİ OKUMA VE TEMİZLEME
        df_raw = pd.read_excel(uploaded_file, header=6)
        df = df_raw.iloc[:, 0:6].dropna(subset=['Koltuk Grubu', 'Fiyat']).copy()
        df = df[~df['Koltuk Grubu'].str.contains("TOPLAM|Fiyat Bazında", na=False, case=False)]
        
        for col in ['Fiyat', 'Stok', 'Kalan Stok']:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
        df['Satılan'] = df['Stok'] - df['Kalan Stok']

        # 2. AKILLI KATEGORİZASYON (Semantik Gruplama)
        def categorize(name):
            name_clean = str(name).replace('İ', 'i').replace('I', 'ı').lower()
            kat_match = re.search(r'(\d+)\.\s*kategori', name_clean)
            if kat_match: return f"{kat_match.group(1)}. Kategori"
            elif "sahne önü" in name_clean or "sahne onu" in name_clean: return "Sahne Önü"
            elif "protokol" in name_clean: return "Protokol"
            elif "gold" in name_clean: return "Gold"
            elif "silver" in name_clean: return "Silver"
            elif "vip" in name_clean: return "VIP"
            else: return "Diğer"

        df['Ana Kategori'] = df['Koltuk Grubu'].apply(categorize)

        # 3. KATEGORİ BAZLI KONSOLİDASYON
        konsolide_df = df.groupby('Ana Kategori').agg({
            'Stok': 'sum',
            'Satılan': 'sum',
            'Kalan Stok': 'sum',
            'Fiyat': 'mean' 
        }).reset_index()

        konsolide_df['Doluluk Oranı'] = konsolide_df.apply(
            lambda x: x['Satılan'] / x['Stok'] if x['Stok'] > 0 else 0, axis=1
        )
        konsolide_df['Mevcut Ciro'] = konsolide_df['Satılan'] * konsolide_df['Fiyat']

        # 4. V4.0 DİNAMİK FİYAT VE BOT YORUM ALGORİTMASI
        def dinamik_bot_karari(row):
            if row['Stok'] == 0: 
                return row['Fiyat'], "Aksiyon Yok"
            if row['Kalan Stok'] == 0: 
                return row['Fiyat'], "✅ Sold-Out (Tükendi)"
            
            doluluk = row['Doluluk Oranı']
            mevcut_fiyat = row['Fiyat']
            
            if doluluk >= hedef_doluluk and row['Kalan Stok'] > 0:
                yeni_fiyat = mevcut_fiyat * 1.15
                aksiyon = "🚀 Yüksek Talep! Fiyatı %15 Artır"
            elif doluluk >= 0.60 and row['Kalan Stok'] > 0:
                yeni_fiyat = mevcut_fiyat * 1.05
                aksiyon = "📈 Hızlı Erime. Fiyatı %5 Artır"
            elif doluluk <= 0.25 and row['Satılan'] > 0:
                yeni_fiyat = mevcut_fiyat * 0.90
                aksiyon = "📉 Yavaş Satış. %10 İndirim veya Paket Çık"
            elif doluluk == 0:
                yeni_fiyat = mevcut_fiyat * 0.85
                aksiyon = "⚠️ Atıl Stok! %15 Flash İndirim veya B2B Sat"
            else:
                yeni_fiyat = mevcut_fiyat
                aksiyon = "⏳ Optimum Seyir. Bekle."

            return yeni_fiyat, aksiyon

        konsolide_df[['Önerilen Fiyat (TL)', 'Bot Aksiyonu']] = konsolide_df.apply(dinamik_bot_karari, axis=1, result_type="expand")

        # 5. MANUEL FİYAT SÜTUNU VE "SESSION STATE" ENTEGRASYONU
        # Başlangıçta botun önerisini manuel fiyat olarak atıyoruz
        sutun_sirasi = konsolide_df.columns.get_loc('Önerilen Fiyat (TL)') + 1
        konsolide_df.insert(sutun_sirasi, '✍️ Manuel Yeni Fiyat', konsolide_df['Önerilen Fiyat (TL)'])

        # EĞER KULLANICI TABLODAN FİYAT DEĞİŞTİRDİYSE, BU DEĞİŞİKLİĞİ YAKALA VE UYGULA
        if "bilet_tablosu" in st.session_state:
            degisiklikler = st.session_state["bilet_tablosu"].get("edited_rows", {})
            for row_idx, degisim in degisiklikler.items():
                if "✍️ Manuel Yeni Fiyat" in degisim:
                    # Kullanıcının girdiği yeni değeri ana veri setine kalıcı olarak yazıyoruz
                    konsolide_df.at[row_idx, "✍️ Manuel Yeni Fiyat"] = float(degisim["✍️ Manuel Yeni Fiyat"])

        # 6. YENİDEN HESAPLAMA (Excel mantığı: Kullanıcı fiyat girer girmez toplam ciro hesaplanır)
        konsolide_df['Hedef Sold-Out Ciro (TL)'] = (konsolide_df['✍️ Manuel Yeni Fiyat'] * konsolide_df['Kalan Stok']) + konsolide_df['Mevcut Ciro']

        # --- DASHBOARD GÖRSELLERİ ---
        st.divider()
        
        # ÜST METRİKLER (KPI) - Artık revize edilmiş ciro hedefini gösteriyor
        toplam_stok = int(konsolide_df['Stok'].sum())
        toplam_satilan = int(konsolide_df['Satılan'].sum())
        genel_doluluk = (toplam_satilan / toplam_stok) * 100 if toplam_stok > 0 else 0
        mevcut_toplam_ciro = konsolide_df['Mevcut Ciro'].sum()
        potansiyel_maks_ciro = konsolide_df['Hedef Sold-Out Ciro (TL)'].sum()

        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Toplam Kapasite", f"{toplam_stok}")
        col2.metric("Satılan Bilet", f"{toplam_satilan}")
        col3.metric("Genel Doluluk", f"%{genel_doluluk:.1f}")
        col4.metric("Kazanılan Ciro", f"₺{mevcut_toplam_ciro:,.0f}")
        col5.metric("🔥 Hedef Sold-Out Ciro", f"₺{potansiyel_maks_ciro:,.0f}")

        st.divider()

        # ANA TABLO
        st.markdown("### 🤖 V4.0 Kategori Bazlı Dinamik Fiyatlandırma ve Bot Önerileri")
        
        format_dict = {
            'Stok': '{:,.0f}',
            'Satılan': '{:,.0f}',
            'Kalan Stok': '{:,.0f}',
            'Fiyat': '₺{:,.0f}',
            'Doluluk Oranı': '{:.1%}',
            'Mevcut Ciro': '₺{:,.0f}',
            'Önerilen Fiyat (TL)': '₺{:,.0f}',
            '✍️ Manuel Yeni Fiyat': '{:.0f}', 
            'Hedef Sold-Out Ciro (TL)': '₺{:,.0f}'
        }
        
        kilitli_sutunlar = [col for col in konsolide_df.columns if col != '✍️ Manuel Yeni Fiyat']

        # Tabloya 'key="bilet_tablosu"' ekledik. Bu sayede girilen değişiklikleri üstte yakalayabiliyoruz.
        st.data_editor(
            konsolide_df.style.format(format_dict).map(
                lambda x: 'background-color: #d4edda' if '🚀' in str(x) or '✅' in str(x) else 
                          ('background-color: #f8d7da' if '⚠️' in str(x) or '📉' in str(x) else ''), 
                subset=['Bot Aksiyonu']
            ), 
            use_container_width=True,
            disabled=kilitli_sutunlar,
            key="bilet_tablosu"
        )

        # GRAFİK
        st.markdown("### 📈 Kategori Doluluk Hızları")
        fig = px.bar(konsolide_df, x="Ana Kategori", y="Doluluk Oranı", 
                     text="Doluluk Oranı", color="Doluluk Oranı", 
                     color_continuous_scale="RdYlGn",
                     title="Hangi Kategori Ne Kadar Doldu?")
        fig.update_traces(texttemplate='%{text:.1%}', textposition='outside')
        fig.update_layout(yaxis=dict(tickformat=".0%"))
        st.plotly_chart(fig, use_container_width=True)

else:
    st.info("Lütfen güncel Bilet Satış (Örn: Erdal Erzincan Konseri) Excel raporunuzu yükleyin.")
