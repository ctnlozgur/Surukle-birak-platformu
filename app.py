import streamlit as st
import pandas as pd
import re
import plotly.express as px

# --- SAYFA AYARLARI VE BAŞLIK ---
st.set_page_config(page_title="V4.0 Dinamik Biletleme & Fiyat Botu", layout="wide", page_icon="🎫")

st.title("🎫 V4.0 Dinamik Biletleme ve Fiyatlandırma Botu")
st.markdown("Etkinlik satış raporunu aşağıya sürükleyin. Süper bilet ciroları çifte sayımdan arındırılır; Davetiye biletler ciro hesabından otomatik düşülerek gerçek gelir hesaplanır.")

# --- 🧠 KALICI HAFIZA SİSTEMİ ---
if "kalici_fiyatlar" not in st.session_state:
    st.session_state.kalici_fiyatlar = {}
if "ana_kalici_fiyatlar" not in st.session_state:
    st.session_state.ana_kalici_fiyatlar = {}

# --- KULLANICI GİRDİLERİ (YAN MENÜ) ---
with st.sidebar:
    st.header("⚙️ Etkinlik Ayarları")
    hedef_doluluk = st.slider("Hedef Doluluk Oranı (%)", min_value=50, max_value=100, value=85) / 100
    st.info("Algoritma, bu hedef doluluğa ve biletlerin erime hızına göre fiyat önerileri sunar.")
    
    st.divider()
    if st.button("🔄 Manuel Fiyatları Sıfırla", use_container_width=True):
        st.session_state.kalici_fiyatlar = {}
        st.session_state.ana_kalici_fiyatlar = {}
        st.rerun()

# --- DOSYA YÜKLEME ALANI ---
uploaded_file = st.file_uploader("Bilet Satış Raporunu Yükleyin (.xlsx)", type=["xlsx"])

if uploaded_file is not None:
    with st.spinner('Rapor işleniyor, Gerçek cirolar ayrıştırılıyor...'):
        
        # 1. HAM VERİYİ VE TARİHİ OKUMA
        df_raw = pd.read_excel(uploaded_file, header=None)
        
        try:
            tarih_metni = str(df_raw.iloc[2, 1])
            etkinlik_tarihi = pd.to_datetime(tarih_metni)
            bugun = pd.to_datetime("2026-09-10") 
            kalan_gun = (etkinlik_tarihi - bugun).days
        except:
            kalan_gun = "Bilinmiyor"

        # Fiyat Bazında Gruplama Satırını Bul (Sınır olarak kullanmak için)
        fiyat_bazinda_idx = df_raw[df_raw[0].astype(str).str.contains("Fiyat Bazında Gruplama", na=False)].index
        end_idx = fiyat_bazinda_idx[0] if len(fiyat_bazinda_idx) > 0 else len(df_raw)

        # 2. ANA BİLETLERİ AYIKLAMA
        df_main = df_raw.iloc[7:end_idx, 0:6].copy()
        df_main.columns = ['Alt Kategori', 'Fiyat', 'İnd. Fiyat', 'Stok', 'Kalan Stok', 'Satış Durumu']
        df_main = df_main.dropna(subset=['Alt Kategori', 'Fiyat'])
        df_main = df_main[~df_main['Alt Kategori'].astype(str).str.contains("TOPLAM|Fiyat Bazında", na=False, case=False)]
        df_main = df_main[~df_main['Alt Kategori'].apply(lambda x: str(x).isnumeric() or str(x).replace('.','',1).isdigit())]
        
        # Boşluk Temizliği
        df_main['Alt Kategori'] = df_main['Alt Kategori'].astype(str).str.strip()
        
        for col in ['Fiyat', 'İnd. Fiyat', 'Stok', 'Kalan Stok']:
            df_main[col] = pd.to_numeric(df_main[col], errors='coerce').fillna(0.0)
            
        df_main['Satılan'] = df_main['Stok'] - df_main['Kalan Stok']
        df_main['Gecerli_Fiyat'] = df_main['İnd. Fiyat'] 

        # 3. SÜPER BİLETLERİ AYIKLAMA
        df_super = pd.DataFrame()
        if df_raw.shape[1] >= 14:
            super_baslik = str(df_raw.iloc[6, 7])
            if "Süper Bilet" in super_baslik:
                df_super = df_raw.iloc[7:end_idx, 7:14].copy()
                df_super.columns = ['Alt Kategori', 'İndirim Türü', 'İndirim Oranı', 'Fiyat', 'SB İnd. Fiyat', 'Satılan', 'Kalan Stok']
                df_super = df_super.dropna(subset=['Alt Kategori', 'Fiyat'])
                
                df_super['Alt Kategori'] = df_super['Alt Kategori'].astype(str).str.strip()
                
                for col in ['Fiyat', 'SB İnd. Fiyat', 'Satılan', 'Kalan Stok']:
                    df_super[col] = pd.to_numeric(df_super[col], errors='coerce').fillna(0.0)

        # 4. YENİ BİRLEŞTİRME VE ÇİFTE SAYIM (SPLIT) ALGORİTMA
        if not df_super.empty:
            df_super_agg = df_super.groupby('Alt Kategori', as_index=False)['Satılan'].sum()
            df_super_agg.rename(columns={'Satılan': 'Toplam_SB_Satılan'}, inplace=True)

            merged = pd.merge(df_main, df_super_agg, on='Alt Kategori', how='left')
            merged['Toplam_SB_Satılan'] = merged['Toplam_SB_Satılan'].fillna(0.0)
            
            merged['Normal_Satılan'] = merged['Satılan'] - merged['Toplam_SB_Satılan']
            merged['Normal_Satılan'] = merged['Normal_Satılan'].apply(lambda x: x if x > 0 else 0)
            
            df_normal = merged.copy()
            df_normal['Satılan'] = df_normal['Normal_Satılan']
            df_normal['Stok'] = df_normal['Satılan'] + df_normal['Kalan Stok']
            df_normal['Is_Super_Bilet'] = False
            df_normal['Fiyat'] = df_normal['Gecerli_Fiyat'] 
            
            df_sb = df_super[df_super['Satılan'] > 0].copy()
            df_sb['Alt Kategori'] = df_sb['Alt Kategori'] + " (Süper Bilet - " + df_sb['SB İnd. Fiyat'].astype(str) + " ₺)"
            df_sb['Fiyat'] = df_sb['SB İnd. Fiyat'] 
            df_sb['Satılan'] = df_sb['Satılan']
            df_sb['Kalan Stok'] = 0.0
            df_sb['Stok'] = df_sb['Satılan']
            df_sb['Is_Super_Bilet'] = True
            
            df = pd.concat([
                df_normal[['Alt Kategori', 'Fiyat', 'Stok', 'Kalan Stok', 'Is_Super_Bilet', 'Satılan']], 
                df_sb[['Alt Kategori', 'Fiyat', 'Stok', 'Kalan Stok', 'Is_Super_Bilet', 'Satılan']]
            ], ignore_index=True)
        else:
            df = df_main.copy()
            df['Fiyat'] = df['Gecerli_Fiyat']
            df = df[['Alt Kategori', 'Fiyat', 'Stok', 'Kalan Stok', 'Satılan']]
            df['Is_Super_Bilet'] = False

        # 5. KATEGORİZASYON 
        def categorize(name):
            name_clean = str(name).replace('İ', 'i').replace('I', 'ı').lower()
            kat_match = re.search(r'(\d+)\.\s*kategori', name_clean)
            cift_mi = " (Çift Kişilik)" if "çift" in name_clean or "cift" in name_clean else ""
            
            if "davetiye" in name_clean or "davet" in name_clean: return f"Davetiye{cift_mi}"
            elif kat_match: return f"{kat_match.group(1)}. Kategori{cift_mi}"
            elif "sahne önü" in name_clean or "sahne onu" in name_clean: return f"Sahne Önü{cift_mi}"
            elif "protokol" in name_clean: return f"Protokol{cift_mi}"
            elif "gold" in name_clean: return f"Gold{cift_mi}"
            elif "silver" in name_clean: return f"Silver{cift_mi}"
            elif "vip" in name_clean: return f"VIP{cift_mi}"
            elif "genel giriş" in name_clean or "genel giris" in name_clean: return f"Genel Giriş{cift_mi}"
            elif "ayakta" in name_clean: return f"Ayakta{cift_mi}"
            else: return f"Diğer{cift_mi}"

        df['Ana Kategori'] = df['Alt Kategori'].apply(categorize)

        # 6. ALT KATEGORİ KONSOLİDASYONU
        konsolide_df = df.groupby(['Ana Kategori', 'Alt Kategori', 'Is_Super_Bilet']).agg({
            'Stok': 'sum',
            'Satılan': 'sum',
            'Kalan Stok': 'sum',
            'Fiyat': 'mean'
        }).reset_index()

        konsolide_df['Doluluk Oranı'] = konsolide_df.apply(
            lambda x: x['Satılan'] / x['Stok'] if x['Stok'] > 0 else 0, axis=1
        )
        
        # --- CİRO SIFIRLAMA KURALI (SADECE DAVETİYE SIFIRLANIR) ---
        konsolide_df['Mevcut Ciro'] = konsolide_df.apply(
            lambda x: 0.0 if 'Davetiye' in x['Ana Kategori'] else (x['Satılan'] * x['Fiyat']), axis=1
        )

        # 7. BOT ALGORİTMASI
        def dinamik_bot_karari(row):
            if float(row['Stok']) <= 0: return row['Fiyat'], "Aksiyon Yok"
            if float(row['Kalan Stok']) <= 0: return row['Fiyat'], "✅ Sold-Out (Tükendi)"
            
            doluluk = row['Doluluk Oranı']
            mevcut_fiyat = row['Fiyat']
            
            if doluluk >= hedef_doluluk and row['Kalan Stok'] > 0:
                return mevcut_fiyat * 1.15, "🚀 Yüksek Talep! Fiyatı %15 Artır"
            elif doluluk >= 0.60 and row['Kalan Stok'] > 0:
                return mevcut_fiyat * 1.05, "📈 Hızlı Erime. Fiyatı %5 Artır"
            elif doluluk <= 0.25 and row['Satılan'] > 0:
                return mevcut_fiyat * 0.90, "📉 Yavaş Satış. %10 İndirim"
            elif doluluk == 0:
                return mevcut_fiyat * 0.85, "⚠️ Atıl Stok! %15 Flash İndirim"
            else:
                return mevcut_fiyat, "⏳ Optimum Seyir. Bekle."

        konsolide_df[['Önerilen Fiyat (TL)', 'Bot Aksiyonu']] = konsolide_df.apply(dinamik_bot_karari, axis=1, result_type="expand")

        # 8. SIRALAMA
        konsolide_df['Sifir_Stok_Mu'] = konsolide_df['Kalan Stok'] <= 0
        konsolide_df = konsolide_df.sort_values(by=['Sifir_Stok_Mu', 'Ana Kategori', 'Alt Kategori']).reset_index(drop=True)
        
        mevcut_sutunlar = konsolide_df.columns.tolist()
        mevcut_sutunlar.remove('Alt Kategori')
        mevcut_sutunlar.remove('Ana Kategori')
        yeni_sutun_sirasi = ['Alt Kategori', 'Ana Kategori'] + mevcut_sutunlar
        konsolide_df = konsolide_df[yeni_sutun_sirasi]

        # 9. ALT KATEGORİ MANUEL FİYAT VE HAFIZA
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

        # Davetiyelerin hedef ciro tahmini de 0 kalmalıdır
        konsolide_df['Hedef Sold-Out Ciro (TL)'] = konsolide_df.apply(
            lambda x: 0.0 if 'Davetiye' in x['Ana Kategori'] else (x['✍️ Manuel Yeni Fiyat'] * x['Kalan Stok']) + x['Mevcut Ciro'], axis=1
        )

        # 10. ANA KATEGORİ KONSOLİDASYONU
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
        
        ana_kategori_df[['Önerilen Ort. Fiyat', 'Genel Bot Aksiyonu']] = ana_kategori_df.apply(dinamik_bot_karari, axis=1, result_type="expand")

        ana_kategori_df['Varsayılan Fiyat'] = ana_kategori_df.apply(
            lambda x: 0.0 if 'Davetiye' in x['Ana Kategori'] else (
                (x['Hedef Sold-Out Ciro (TL)'] - x['Mevcut Ciro']) / x['Kalan Stok'] if x['Kalan Stok'] > 0 else x['Önerilen Ort. Fiyat']
            ), axis=1
        )

        sutun_sirasi_ana = ana_kategori_df.columns.get_loc('Önerilen Ort. Fiyat') + 1
        ana_kategori_df.insert(sutun_sirasi_ana, '✍️ Manuel Yeni Fiyat', ana_kategori_df['Varsayılan Fiyat'])

        for i, row in ana_kategori_df.iterrows():
            ana_kat = row['Ana Kategori']
            if ana_kat in st.session_state.ana_kalici_fiyatlar:
                ana_kategori_df.loc[i, '✍️ Manuel Yeni Fiyat'] = st.session_state.ana_kalici_fiyatlar[ana_kat]

        if "ana_tablo" in st.session_state:
            degisiklikler_ana = st.session_state["ana_tablo"].get("edited_rows", {})
            for row_idx, degisim in degisiklikler_ana.items():
                if "✍️ Manuel Yeni Fiyat" in degisim:
                    yeni_deger = float(degisim["✍️ Manuel Yeni Fiyat"])
                    ana_kategori_df.loc[row_idx, "✍️ Manuel Yeni Fiyat"] = yeni_deger
                    ana_kat = ana_kategori_df.loc[row_idx, 'Ana Kategori']
                    st.session_state.ana_kalici_fiyatlar[ana_kat] = yeni_deger

        ana_kategori_df['Hedef Sold-Out Ciro (TL)'] = ana_kategori_df.apply(
            lambda x: 0.0 if 'Davetiye' in x['Ana Kategori'] else (x['✍️ Manuel Yeni Fiyat'] * x['Kalan Stok']) + x['Mevcut Ciro'], axis=1
        )
        
        ana_kategori_df['Sifir_Stok_Mu'] = ana_kategori_df['Kalan Stok'] <= 0
        ana_kategori_df = ana_kategori_df.sort_values(by=['Sifir_Stok_Mu', 'Ana Kategori']).reset_index(drop=True)
        
        ana_kategori_df = ana_kategori_df[['Ana Kategori', 'Stok', 'Satılan', 'Kalan Stok', 'Fiyat', 'Doluluk Oranı', 'Mevcut Ciro', 'Önerilen Ort. Fiyat', '✍️ Manuel Yeni Fiyat', 'Genel Bot Aksiyonu', 'Hedef Sold-Out Ciro (TL)', 'Sifir_Stok_Mu']]

        # 11. TOP KPI 
        toplam_stok = int(ana_kategori_df['Stok'].sum())
        toplam_satilan = int(ana_kategori_df['Satılan'].sum())
        genel_doluluk = (toplam_satilan / toplam_stok) * 100 if toplam_stok > 0 else 0
        mevcut_toplam_ciro = ana_kategori_df['Mevcut Ciro'].sum()
        potansiyel_maks_ciro = ana_kategori_df['Hedef Sold-Out Ciro (TL)'].sum()

        # --- ARAYÜZ ---
        st.divider()
        
        col1, col2, col3, col4, col5, col6 = st.columns(6)
        col1.metric("⏳ Kalan Gün", f"{kalan_gun}")
        col2.metric("Toplam Kapasite", f"{toplam_stok:,.0f}")
        col3.metric("Satılan Bilet", f"{toplam_satilan:,.0f}")
        col4.metric("Genel Doluluk", f"%{genel_doluluk:.1f}")
        col5.metric("Kazanılan Ciro", f"₺{mevcut_toplam_ciro:,.2f}")
        col6.metric("🔥 Tahmini Hedef Ciro", f"₺{potansiyel_maks_ciro:,.2f}")

        st.divider()

        # BÖLÜM 1: ALT KATEGORİ
        st.markdown("### 🤖 V4.0 Alt Kategori Bazlı Detaylı Tablo ve Öneriler")
        
        format_dict_detay = {
            'Stok': '{:,.0f}',
            'Satılan': '{:,.0f}',
            'Kalan Stok': '{:,.0f}',
            'Fiyat': '₺{:,.2f}',
            'Doluluk Oranı': '{:.1%}',
            'Mevcut Ciro': '₺{:,.2f}',
            'Önerilen Fiyat (TL)': '₺{:,.2f}',
            '✍️ Manuel Yeni Fiyat': '{:.2f}', 
            'Hedef Sold-Out Ciro (TL)': '₺{:,.2f}'
        }
        
        kilitli_sutunlar = [col for col in konsolide_df.columns if col != '✍️ Manuel Yeni Fiyat']

        def row_color(row):
            if row.get('Is_Super_Bilet', False):
                return ['background-color: #ffe8cc'] * len(row)
            elif float(row['Kalan Stok']) <= 0:
                return ['background-color: #ffcccc'] * len(row)
            elif '🚀' in str(row['Bot Aksiyonu']) or '✅' in str(row['Bot Aksiyonu']):
                return ['background-color: #d4edda'] * len(row)
            elif '📉' in str(row['Bot Aksiyonu']):
                return ['background-color: #cce5ff'] * len(row)
            elif '⚠️' in str(row['Bot Aksiyonu']):
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

        # BÖLÜM 3: ANA KATEGORİ (DÜZENLENEBİLİR)
        st.markdown("### 📊 Ana Kategori Toplu Özet Görünümü (Düzenlenebilir)")
        
        format_dict_ana = {
            'Stok': '{:,.0f}',
            'Satılan': '{:,.0f}',
            'Kalan Stok': '{:,.0f}',
            'Fiyat': '₺{:,.2f}',
            'Doluluk Oranı': '{:.1%}',
            'Mevcut Ciro': '₺{:,.2f}',
            'Önerilen Ort. Fiyat': '₺{:,.2f}',
            '✍️ Manuel Yeni Fiyat': '{:.2f}', 
            'Hedef Sold-Out Ciro (TL)': '₺{:,.2f}'
        }
        
        kilitli_sutunlar_ana = [col for col in ana_kategori_df.columns if col != '✍️ Manuel Yeni Fiyat']
        
        def row_color_ana(row):
            if float(row['Kalan Stok']) <= 0:
                return ['background-color: #ffcccc'] * len(row)
            elif '🚀' in str(row['Genel Bot Aksiyonu']) or '✅' in str(row['Genel Bot Aksiyonu']):
                return ['background-color: #d4edda'] * len(row)
            elif '📉' in str(row['Genel Bot Aksiyonu']):
                return ['background-color: #cce5ff'] * len(row)
            elif '⚠️' in str(row['Genel Bot Aksiyonu']):
                return ['background-color: #f8d7da'] * len(row)
            return [''] * len(row)

        st.data_editor(
            ana_kategori_df.style.format(format_dict_ana).apply(row_color_ana, axis=1), 
            use_container_width=True,
            disabled=kilitli_sutunlar_ana,
            column_config={
                "Sifir_Stok_Mu": None
            },
            key="ana_tablo"
        )

else:
    st.info("Lütfen güncel Bilet Satış Excel raporunuzu yükleyin.")
