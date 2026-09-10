import streamlit as st
import pandas as pd
import re
import plotly.express as px

# --- SAYFA AYARLARI VE BAŞLIK ---
st.set_page_config(page_title="V4.0 Dinamik Biletleme & Fiyat Botu", layout="wide", page_icon="🎫")

st.title("🎫 V4.0 Dinamik Biletleme ve Fiyatlandırma Botu")
st.markdown("Etkinlik satış raporunu aşağıya sürükleyin. Alt kategori bazlı inceleme yapabilir, Süper Biletleri turuncu, stoksuz ürünleri kırmızı renkte görebilirsiniz. Sayfanın en altında ise Ana Kategori özet tablosu yer almaktadır.")

# --- 🧠 KALICI HAFIZA SİSTEMİ ---
if "kalici_fiyatlar" not in st.session_state:
    st.session_state.kalici_fiyatlar = {}

# --- KULLANICI GİRDİLERİ (YAN MENÜ) ---
with st.sidebar:
    st.header("⚙️ Etkinlik Ayarları")
    hedef_doluluk = st.slider("Hedef Doluluk Oranı (%)", min_value=50, max_value=100, value=85) / 100
    st.info("Algoritma, bu hedef doluluğa ve biletlerin erime hızına göre fiyat önerileri sunar.")

# --- DOSYA YÜKLEME ALANI ---
uploaded_file = st.file_uploader("Bilet Satış Raporunu Yükleyin (.xlsx)", type=["xlsx"])

if uploaded_file is not None:
    with st.spinner('Rapor işleniyor, veriler birleştiriliyor...'):
        
        # 1. HAM VERİYİ VE TARİHİ OKUMA
        df_raw = pd.read_excel(uploaded_file, header=None)
        
        try:
            tarih_metni = str(df_raw.iloc[2, 1])
            etkinlik_tarihi = pd.to_datetime(tarih_metni)
            bugun = pd.to_datetime("2026-09-10") 
            kalan_gun = (etkinlik_tarihi - bugun).days
        except:
            kalan_gun = "Bilinmiyor"

        # 2. ANA BİLETLERİ AYIKLAMA
        df_main = df_raw.iloc[7:, 0:6].copy()
        df_main.columns = ['Alt Kategori', 'Fiyat', 'İnd. Fiyat', 'Stok', 'Kalan Stok', 'Satış Durumu']
        df_main = df_main.dropna(subset=['Alt Kategori', 'Fiyat'])
        df_main = df_main[~df_main['Alt Kategori'].astype(str).str.contains("TOPLAM|Fiyat Bazında", na=False, case=False)]
        df_main = df_main[~df_main['Alt Kategori'].apply(lambda x: str(x).isnumeric() or str(x).replace('.','',1).isdigit())]
        df_main['Is_Super_Bilet'] = False

        # 3. SÜPER BİLETLERİ AYIKLAMA
        df_super = pd.DataFrame()
        if df_raw.shape[1] >= 14:
            super_baslik = str(df_raw.iloc[6, 7])
            if "Süper Bilet" in super_baslik:
                df_super = df_raw.iloc[7:, 7:14].copy()
                df_super.columns = ['Alt Kategori', 'İndirim Türü', 'İndirim Oranı', 'Fiyat', 'SB İnd. Fiyat', 'Satılan', 'Kalan Stok']
                df_super = df_super.dropna(subset=['Alt Kategori', 'Fiyat'])
                
                satilan_num = pd.to_numeric(df_super['Satılan'], errors='coerce').fillna(0)
                kalan_num = pd.to_numeric(df_super['Kalan Stok'], errors='coerce').fillna(0)
                df_super['Stok'] = satilan_num + kalan_num
                
                df_super = df_super[['Alt Kategori', 'Fiyat', 'Stok', 'Kalan Stok']]
                df_super['Is_Super_Bilet'] = True

        df = pd.concat([df_main[['Alt Kategori', 'Fiyat', 'Stok', 'Kalan Stok', 'Is_Super_Bilet']], df_super], ignore_index=True)

        for col in ['Fiyat', 'Stok', 'Kalan Stok']:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
        df['Satılan'] = df['Stok'] - df['Kalan Stok']

        # 4. KATEGORİZASYON
        def categorize(name):
            name_clean = str(name).replace('İ', 'i').replace('I', 'ı').lower()
            kat_match = re.search(r'(\d+)\.\s*kategori', name_clean)
            cift_mi = " (Çift Kişilik)" if "çift" in name_clean or "cift" in name_clean else ""
            
            if kat_match: return f"{kat_match.group(1)}. Kategori{cift_mi}"
            elif "sahne önü" in name_clean or "sahne onu" in name_clean: return f"Sahne Önü{cift_mi}"
            elif "protokol" in name_clean: return f"Protokol{cift_mi}"
            elif "gold" in name_clean: return f"Gold{cift_mi}"
            elif "silver" in name_clean: return f"Silver{cift_mi}"
            elif "vip" in name_clean: return f"VIP{cift_mi}"
            elif "genel giriş" in name_clean or "genel giris" in name_clean: return f"Genel Giriş{cift_mi}"
            elif "ayakta" in name_clean: return f"Ayakta{cift_mi}"
            else: return f"Diğer{cift_mi}"

        df['Ana Kategori'] = df['Alt Kategori'].apply(categorize)

        # 5. ALT KATEGORİ KONSOLİDASYONU (DETAY TABLOSU)
        konsolide_df = df.groupby(['Ana Kategori', 'Alt Kategori', 'Is_Super_Bilet']).agg({
            'Stok': 'sum',
            'Satılan': 'sum',
            'Kalan Stok': 'sum',
            'Fiyat': 'mean' 
        }).reset_index()

        konsolide_df['Doluluk Oranı'] = konsolide_df.apply(
            lambda x: x['Satılan'] / x['Stok'] if x['Stok'] > 0 else 0, axis=1
        )
        konsolide_df['Mevcut Ciro'] = konsolide_df['Satılan'] * konsolide_df['Fiyat']

        # 6. BOT ALGORİTMASI
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

        # 7. SIRALAMA
        konsolide_df['Sifir_Stok_Mu'] = konsolide_df['Kalan Stok'] == 0
        konsolide_df = konsolide_df.sort_values(by=['Sifir_Stok_Mu', 'Ana Kategori', 'Alt Kategori']).reset_index(drop=True)

        # 8. MANUEL FİYAT VE HAFIZA YÖNETİMİ
        sutun_sirasi = konsolide_df.columns.get_loc('Önerilen Fiyat (TL)') + 1
        konsolide_df.insert(sutun_sirasi, '✍️ Manuel Yeni Fiyat', konsolide_df['Önerilen Fiyat (TL)'])

        for i, row in konsolide_df.iterrows():
            alt_kat = row['Alt Kategori']
            if alt_kat in st.session_state.kalici_fiyatlar:
                konsolide_df.loc[i, '✍️ Manuel Yeni Fiyat'] = st.session_state.kalici_fiyatlar[alt_kat]

        if "bilet_tablosu" in st.session_state:
            degisiklikler = st.session_state["bilet_tablosu"].get("edited_rows", {})
            for row_idx, degisim in degisiklikler.items():
                if "✍️ Manuel Yeni Fiyat" in degisim:
                    yeni_deger = float(degisim["✍️ Manuel Yeni Fiyat"])
                    konsolide_df.loc[row_idx, "✍️ Manuel Yeni Fiyat"] = yeni_deger
                    
                    alt_kat = konsolide_df.loc[row_idx, 'Alt Kategori']
                    st.session_state.kalici_fiyatlar[alt_kat] = yeni_deger

        # 9. HEDEF CİRO YENİDEN HESAPLAMA (DETAY TABLOSU İÇİN)
        konsolide_df['Hedef Sold-Out Ciro (TL)'] = (konsolide_df['✍️ Manuel Yeni Fiyat'] * konsolide_df['Kalan Stok']) + konsolide_df['Mevcut Ciro']

        # --- YENİ EKLENEN: ANA KATEGORİ ÖZET TABLOSU HAZIRLIĞI ---
        ana_kategori_df = konsolide_df.groupby('Ana Kategori').agg({
            'Stok': 'sum',
            'Satılan': 'sum',
            'Kalan Stok': 'sum',
            'Mevcut Ciro': 'sum',
            'Hedef Sold-Out Ciro (TL)': 'sum'
        }).reset_index()

        ana_fiyat_df = konsolide_df.groupby('Ana Kategori')['Fiyat'].mean().reset_index()
        ana_kategori_df = pd.merge(ana_kategori_df, ana_fiyat_df, on='Ana Kategori')
        
        ana_kategori_df['Doluluk Oranı'] = ana_kategori_df.apply(
            lambda x: x['Satılan'] / x['Stok'] if x['Stok'] > 0 else 0, axis=1
        )
        
        # Bot kararını Ana Kategori genel durumu için hesapla
        ana_kategori_df[['Önerilen Ort. Fiyat', 'Genel Bot Aksiyonu']] = ana_kategori_df.apply(dinamik_bot_karari, axis=1, result_type="expand")
        
        ana_kategori_df = ana_kategori_df[['Ana Kategori', 'Stok', 'Satılan', 'Kalan Stok', 'Fiyat', 'Doluluk Oranı', 'Mevcut Ciro', 'Önerilen Ort. Fiyat', 'Genel Bot Aksiyonu', 'Hedef Sold-Out Ciro (TL)']]

        # --- DASHBOARD GÖRSELLERİ ARAYÜZÜ ---
        st.divider()
        
        # ÜST METRİKLER (KPI)
        toplam_stok = int(konsolide_df['Stok'].sum())
        toplam_satilan = int(konsolide_df['Satılan'].sum())
        genel_doluluk = (toplam_satilan / toplam_stok) * 100 if toplam_stok > 0 else 0
        mevcut_toplam_ciro = konsolide_df['Mevcut Ciro'].sum()
        potansiyel_maks_ciro = konsolide_df['Hedef Sold-Out Ciro (TL)'].sum()

        col1, col2, col3, col4, col5, col6 = st.columns(6)
        col1.metric("⏳ Kalan Gün", f"{kalan_gun}")
        col2.metric("Toplam Kapasite", f"{toplam_stok}")
        col3.metric("Satılan Bilet", f"{toplam_satilan}")
        col4.metric("Genel Doluluk", f"%{genel_doluluk:.1f}")
        col5.metric("Kazanılan Ciro", f"₺{mevcut_toplam_ciro:,.0f}")
        col6.metric("🔥 Toplam Hedef Ciro", f"₺{potansiyel_maks_ciro:,.0f}")

        st.divider()

        # BÖLÜM 1: ALT KATEGORİ DETAY TABLOSU (DÜZENLENEBİLİR)
        st.markdown("### 🤖 V4.0 Alt Kategori Bazlı Detaylı Tablo ve Öneriler")
        
        format_dict_detay = {
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

        def row_color(row):
            if row['Kalan Stok'] == 0:
                return ['background-color: #ffcccc'] * len(row)
            elif row['Is_Super_Bilet']:
                return ['background-color: #ffe8cc'] * len(row)
            elif '🚀' in str(row['Bot Aksiyonu']) or '✅' in str(row['Bot Aksiyonu']):
                return ['background-color: #d4edda'] * len(row)
            elif '⚠️' in str(row['Bot Aksiyonu']) or '📉' in str(row['Bot Aksiyonu']):
                return ['background-color: #f8d7da'] * len(row)
            return [''] * len(row)

        st.data_editor(
            konsolide_df.style.format(format_dict_detay).apply(row_color, axis=1), 
            use_container_width=True,
            disabled=kilitli_sutunlar,
            column_config={
                "Sifir_Stok_Mu": None, 
                "Is_Super_Bilet": None 
            },
            key="bilet_tablosu"
        )

        # BÖLÜM 2: GRAFİK
        st.markdown("### 📈 Ana Kategori Doluluk Hızları")
        
        fig = px.bar(ana_kategori_df, x="Ana Kategori", y="Doluluk Oranı", 
                     text="Doluluk Oranı", color="Doluluk Oranı", 
                     color_continuous_scale="RdYlGn",
                     title="Hangi Ana Kategori Ne Kadar Doldu?")
        fig.update_traces(texttemplate='%{text:.1%}', textposition='outside')
        fig.update_layout(yaxis=dict(tickformat=".0%"))
        st.plotly_chart(fig, use_container_width=True)

        st.divider()

        # BÖLÜM 3: ANA KATEGORİ TOPLU ÖZET TABLOSU
        st.markdown("### 📊 Ana Kategori Toplu Özet Görünümü")
        st.markdown("Yukarıda yaptığınız manuel fiyat değişikliklerinin kategori geneline (toplam stok ve ciro) yansımasıdır.")
        
        format_dict_ana = {
            'Stok': '{:,.0f}',
            'Satılan': '{:,.0f}',
            'Kalan Stok': '{:,.0f}',
            'Fiyat': '₺{:,.0f}',
            'Doluluk Oranı': '{:.1%}',
            'Mevcut Ciro': '₺{:,.0f}',
            'Önerilen Ort. Fiyat': '₺{:,.0f}',
            'Hedef Sold-Out Ciro (TL)': '₺{:,.0f}'
        }

        st.dataframe(
            ana_kategori_df.style.format(format_dict_ana).map(
                lambda x: 'background-color: #d4edda' if '🚀' in str(x) or '✅' in str(x) else 
                          ('background-color: #f8d7da' if '⚠️' in str(x) or '📉' in str(x) else ''), 
                subset=['Genel Bot Aksiyonu']
            ), 
            use_container_width=True
        )

else:
    st.info("Lütfen güncel Bilet Satış Excel raporunuzu yükleyin.")
