import streamlit as st
import pandas as pd
import numpy as np
import os
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from io import BytesIO
# =========================
# CONFIG
# =========================
st.set_page_config(page_title="Pipette QC Analyzer", layout="wide")
# =========================
# CONSTANTS
# =========================
COLUMN_MAPPING = {
    "Kết quả đo lần 1 (µL)": "KQĐ L1 (µL)",
    "Kết quả đo lần 2 (µL)": "KQĐ L2 (µL)",
    "Kết quả đo lần 3 (µL)": "KQĐ L3 (µL)",
    "Điểm đo (µL)": "Điểm đo (µL)",
    "Thể tích danh định (µL)": "Thể tích danh định (µL)",
    "Mức kiểm tra (%)": "Mức kiểm tra (%)"
}
ACCEPTANCE_CRITERIA = {
    1000: (8, "Sai số ± 8 µL"),
    200: (1.6, "Sai số ± 1,6 µL"),
    20: (0.2, "Sai số ± 0,2 µL"),
    2.5: (0.0625, "Sai số ± 0,0625 µL")
}
CV_CRITERIA = {
    (1000, 1000): 0.2,
    (1000, 500): 0.4,
    (1000, 100): 1.0,
    (200, 200): 0.2,
    (200, 100): 0.4,
    (200, 20): 1.0,
    (20, 20): 0.4,
    (20, 10): 0.8,
    (20, 2): 2.0,
    (2.5, 2.5): 0.6,
    (2.5, 1.25): 1.2,
    (2.5, 0.25): 3.0,
}
FINAL_COLUMNS = [
    "STT", "Mã TSCĐ", "Tên thiết bị", "Ký mã hiệu", "Số seri",
    "Thể tích danh định (µL)", "Mức kiểm tra (%)", "Điểm đo (µL)", 
    "KQĐ L1 (µL)", "KQĐ L2 (µL)", "KQĐ L3 (µL)",
    "Trung bình (µL)", "SD (µL)", "CV (%)",
    "Số hiệu chính (µL)", "Tiêu chuẩn chấp nhận", 
    "Đánh giá sai số", "Đánh giá độ lặp lại", "Đánh giá"
]
# =========================
# CORE LOGIC
# =========================
def render_metadata_form():
    st.subheader("Thông tin kiểm tra")
    with st.form("metadata_form"):
        col1, col2 = st.columns(2)
        with col1:
            ngay = st.date_input("Ngày thực hiện:")
            nguoi = st.text_input("Họ tên người thực hiện:")
            dia_diem = st.text_input("Địa điểm thực hiện:")
        with col2:
            ten_tb = st.text_input("Tên thiết bị sử dụng kiểm tra:")
            ky_mh = st.text_input("Ký mã hiệu:")
            so_seri = st.text_input("Số seri:")
        submitted = st.form_submit_button("Xác nhận")
        if submitted:
            st.session_state.metadata = {
                "ngay": ngay.strftime("%d/%m/%Y"),
                "nguoi": nguoi,
                "dia_diem": dia_diem,
                "ten_tb": ten_tb,
                "ky_mh": ky_mh,
                "so_seri": so_seri
            }
            st.success("Đã lưu thông tin kiểm tra")
    return st.session_state.get("metadata", None)

def load_data(file) -> pd.DataFrame:
    df = pd.read_excel(file)
    df = df.rename(columns=COLUMN_MAPPING)
    return df

def calculate_metrics(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    measure_cols = ["KQĐ L1 (µL)", "KQĐ L2 (µL)", "KQĐ L3 (µL)"]
    # ===== Mean =====
    df["Trung bình (µL)"] = df[measure_cols].mean(axis=1)
    # ===== SD (sample standard deviation, ddof=1) =====
    df["SD (µL)"] = df[measure_cols].std(axis=1, ddof=1)
    # ===== CV% =====
    df["CV (%)"] = np.where(
        df["Trung bình (µL)"] != 0,
        (df["SD (µL)"] / df["Trung bình (µL)"]) * 100,
        np.nan
    )
    # ===== Systematic error =====
    df["Số hiệu chính (µL)"] = df["Điểm đo (µL)"] - df["Trung bình (µL)"]
    # ===== Acceptance + evaluation =====
    acc_texts = []
    acc_eval = []
    cv_eval = []
    cv_limits = []
    final_eval = []
    for _, row in df.iterrows():
        nominal = round(row["Thể tích danh định (µL)"], 2)
        target  = round(row["Điểm đo (µL)"], 2)
        # ===== ACCURACY =====
        acc_val, acc_txt = ACCEPTANCE_CRITERIA.get(nominal, (np.nan, "N/A"))
        acc_texts.append(acc_txt)
        if pd.isna(acc_val):
            acc_result = "N/A"
        elif abs(row["Số hiệu chính (µL)"]) <= acc_val:
            acc_result = "Đạt"
        else:
            acc_result = "Không đạt"
        acc_eval.append(acc_result)
        # ===== PRECISION (CV%) theo bảng 2 chiều =====
        key = (nominal, target)
        cv_limit = CV_CRITERIA.get(key, np.nan)
        cv_limits.append(cv_limit)
        if pd.isna(cv_limit) or pd.isna(row["CV (%)"]):
            cv_result = "N/A"
        elif row["CV (%)"] <= cv_limit:
            cv_result = "Đạt"
        else:
            cv_result = "Không đạt"
        cv_eval.append(cv_result)
        # ===== FINAL =====
        if acc_result == "Đạt" and cv_result == "Đạt":
            final = "Đạt"
        else:
            final = "Không đạt"
        final_eval.append(final)
    # ===== ASSIGN BACK =====
    df["Tiêu chuẩn chấp nhận"] = acc_texts
    df["Đánh giá sai số"] = acc_eval
    df["Đánh giá độ lặp lại"] = cv_eval
    df["Đánh giá"] = final_eval
    return df

def format_output(df: pd.DataFrame) -> pd.DataFrame:
    return df[FINAL_COLUMNS]
# =========================
# EXPORT
# =========================
from io import BytesIO

def export_excel(df: pd.DataFrame) -> BytesIO:
    buffer = BytesIO()

    df_excel = df.copy()

    # ===== ENSURE NUMERIC =====
    cols_2dp = ["Thể tích danh định (µL)", 
                "Mức kiểm tra (%)", 
                "Điểm đo (µL)", 
                "KQĐ L1 (µL)", 
                "KQĐ L2 (µL)", 
                "KQĐ L3 (µL)", 
                "Trung bình (µL)",
                "SD (µL)", 
                "CV (%)", 
                "Số hiệu chính (µL)"]
    for col in cols_2dp:
        if col in df_excel.columns:
            df_excel[col] = pd.to_numeric(df_excel[col], errors="coerce")
    # ===== FORMAT MÃ TSCĐ (leading zero) =====
    if "Mã TSCĐ" in df_excel.columns:
        df_excel["Mã TSCĐ"] = pd.to_numeric(df_excel["Mã TSCĐ"], errors="coerce")
    # ===== WRITE EXCEL =====
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        df_excel.to_excel(writer, index=False, sheet_name="QC")
        workbook  = writer.book
        worksheet = writer.sheets["QC"]
        # ===== FORMAT DEFINITIONS =====
        border = 1
        fmt_header = workbook.add_format({
            'bold': True,
            'align': 'center',
            'valign': 'vcenter',
            'border': border
        })
        fmt_text_left = workbook.add_format({
            'align': 'left',
            'valign': 'vcenter',
            'border': border
        })
        fmt_text_center = workbook.add_format({
            'align': 'center',
            'valign': 'vcenter',
            'border': border
        })
        fmt_tscd = workbook.add_format({
            'num_format': '0000',   # 👉 luôn 4 chữ số
            'align': 'center',
            'valign': 'vcenter',
            'border': border
        })
        fmt_num_2 = workbook.add_format({
            'num_format': '0.00',
            'align': 'right',
            'border': border
        })
        # ===== HEADER =====
        for col_num, col_name in enumerate(df_excel.columns):
            worksheet.write(0, col_num, col_name, fmt_header)
        col_map = {col: i for i, col in enumerate(df_excel.columns)}
        n_rows = len(df_excel)
        # ===== APPLY FORMAT TO DATA CELLS =====
        # Mã TSCĐ (4 digit + center)
        if "Mã TSCĐ" in col_map:
            col = col_map["Mã TSCĐ"]
            worksheet.set_column(col, col, 12, fmt_tscd)
        # Text left
        text_cols = ["Tên thiết bị"]
        for col_name in text_cols:
            if col_name in col_map:
                col = col_map[col_name]
                worksheet.set_column(col, col, 20, fmt_text_left)
        # Center columns
        center_cols = ["STT", "Ký mã hiệu", "Số seri", "Mức kiểm tra (%)", "Tiêu chuẩn chấp nhận", "Đánh giá sai số", "Đánh giá độ lặp lại", "Đánh giá"]
        for col_name in center_cols:
            if col_name in col_map:
                col = col_map[col_name]
                worksheet.set_column(col, col, 14, fmt_text_center)
        # 2 decimal
        for col_name in cols_2dp:
            if col_name in col_map:
                col = col_map[col_name]
                worksheet.set_column(col, col, 16, fmt_num_2)
        # ===== FREEZE HEADER =====
        worksheet.freeze_panes(1, 0)
    buffer.seek(0)
    return buffer

class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []
    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()
    def save(self):
        total_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_number(total_pages)
            super().showPage()
        super().save()
    def draw_page_number(self, total_pages):
        page_num = self._pageNumber
        text = f"{page_num}/{total_pages}"
        # đặt giữa đáy trang
        self.setFont("Times", 10)
        width, height = self._pagesize
        self.drawCentredString(width / 2, 5 * mm, text)

def export_pdf(df: pd.DataFrame, metadata=None) -> BytesIO:
    buffer = BytesIO()
    # ===== FORMAT DATA FOR DISPLAY =====
    df_display = df.copy()
    # Các cột 4 chữ số thập phân
    num_cols = ["Thể tích danh định (µL)", 
                "Mức kiểm tra (%)", 
                "Điểm đo (µL)", 
                "KQĐ L1 (µL)", 
                "KQĐ L2 (µL)", 
                "KQĐ L3 (µL)", 
                "Trung bình (µL)", 
                "SD (µL)", 
                "CV (%)",
                "Số hiệu chính (µL)"]
    for col in num_cols:
        if col in df_display.columns:
            df_display[col] = pd.to_numeric(df_display[col], errors="coerce")
            df_display[col] = df_display[col].map(
                lambda x: f"{x:.2f}" if pd.notnull(x) else ""
            )
    # Register font
    pdfmetrics.registerFont(TTFont("Times", "fonts/times.ttf"))
    pdfmetrics.registerFont(TTFont("Times-Bold", "fonts/timesb.ttf"))
    pdfmetrics.registerFont(TTFont("Times-Italic", "fonts/timesi.ttf"))
    pdfmetrics.registerFont(TTFont("Times-BoldItalic", "fonts/timesbi.ttf"))
    # Landscape A4
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=10,
        rightMargin=10,
        topMargin=10,
        bottomMargin=10
    )
    styles = getSampleStyleSheet()
    elements = []
    # ===== HEADER =====
    if metadata:
        elements.append(Paragraph("<b>BÁO CÁO KIỂM TRA PIPETTE</b>", styles["Title"]))
        elements.append(Spacer(1, 12))
        elements.append(Paragraph(f"Ngày thực hiện: {metadata['ngay']}", styles["Normal"]))
        elements.append(Paragraph(f"Người thực hiện: {metadata['nguoi']}", styles["Normal"]))
        elements.append(Paragraph(f"Địa điểm: {metadata['dia_diem']}", styles["Normal"]))
        elements.append(Spacer(1, 8))
        # ===== THÔNG TIN THIẾT BỊ =====
        elements.append(Paragraph(f"Tên thiết bị: {metadata.get('ten_tb','')}", styles["Normal"]))
        elements.append(Paragraph(f"Ký mã hiệu: {metadata.get('ky_mh','')}", styles["Normal"]))
        elements.append(Paragraph(f"Số seri: {metadata.get('so_seri','')}", styles["Normal"]))
        elements.append(Spacer(1, 20))
    # Convert data
    data = [df_display.columns.tolist()] + df_display.values.tolist()
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Times"),
        ("FONTNAME", (0, 0), (-1, 0), "Times-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    elements.append(table)
    elements.append(Spacer(1, 30))
    if metadata:
        # Căn phải bằng Paragraph style
        styles = getSampleStyleSheet()
        right_style = styles["Normal"]
        right_style.alignment = 2  # 0=left, 1=center, 2=right
        elements.append(Paragraph("Người thực hiện", right_style))
        elements.append(Spacer(1, 12))  
        elements.append(Paragraph("Nhân viên Phòng CNSH Y Dược", right_style))
        elements.append(Spacer(1, 50))  # khoảng trống để ký tay
        elements.append(Paragraph(f"<b>{metadata['nguoi']}</b>", right_style))
    doc.build(elements, canvasmaker=NumberedCanvas)
    buffer.seek(0)
    return buffer
# =========================
# UI LAYER
# =========================
def render_header():
    img_path = "pipette_check.png"
    # Hiển thị banner nếu tồn tại
    if os.path.exists(img_path):
        st.image(img_path, use_container_width=True)
    st.title("Pipette QC Analyzer")
    st.caption("Upload Excel → Calculate QC → Export Excel/PDF")

def render_uploader():
    return st.file_uploader("Tải lên file Excel (.xlsx)", type=["xlsx"])

def render_table(df: pd.DataFrame):
    format_dict = {}
    cols_2dp = [
        "Thể tích danh định (µL)",
        "Điểm đo (µL)",
        "KQĐ L1 (µL)",
        "KQĐ L2 (µL)",
        "KQĐ L3 (µL)",
        "Trung bình (µL)",
        "SD (µL)",
        "CV (%)",
        "Số hiệu chính (µL)"
    ]
    # Build format dict an toàn
    for col in cols_2dp:
        if col in df.columns:
            format_dict[col] = "{:.2f}"
    # ===== HIGHLIGHT FUNCTION =====
    def highlight_pass_fail(val):
        if val == "Không đạt":
            return "color: red; font-weight: bold"
        elif val == "Đạt":
            return "color: green"
        return ""
    st.dataframe(
        df.style
          .format(format_dict)
          .map(
              highlight_pass_fail,
              subset=[
                  col for col in [
                      "Đánh giá sai số",
                      "Đánh giá độ lặp lại"
                      "Đánh giá"
                  ] if col in df.columns
              ]
          ),
        use_container_width=True
    )
def render_downloads(df: pd.DataFrame):
    col1, col2 = st.columns(2)
    with col1:
        excel_buffer = export_excel(df)
        st.download_button(
            "Tải xuống file Excel",
            excel_buffer,
            file_name="pipette_qc.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    with col2:
        pdf_buffer = export_pdf(df, st.session_state.get("metadata"))
        st.download_button(
            "Tải xuống file PDF",
            pdf_buffer,
            file_name="pipette_qc.pdf",
            mime="application/pdf"
        )
# =========================
# MAIN APP
# =========================
def main():
    render_header()
    # ===== METADATA =====
    metadata = render_metadata_form()
    if metadata is None:
        st.info("Vui lòng nhập thông tin kiểm tra trước.")
        return
    # ===== FILE UPLOAD =====
    file = render_uploader()
    if file is None:
        st.info("Tải lên file để bắt đầu.")
        return
    # ===== PROCESSING =====
    try:
        df_raw = load_data(file)
        df_processed = calculate_metrics(df_raw)
        df_final = format_output(df_processed)
        # ===== DISPLAY =====
        render_table(df_final)
        # ===== DOWNLOAD =====
        render_downloads(df_final)
    except Exception as e:
        st.error(f"Lỗi xử lý dữ liệu: {e}")
# ===== ENTRY POINT (BẮT BUỘC PHẢI Ở NGOÀI) =====
if __name__ == "__main__":
    main()
# =========================
# requirements.txt
# =========================
# streamlit
# pandas
# numpy
# reportlab