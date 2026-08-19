"""
IKIO Vendor Registration Portal
--------------------------------
Streamlit + SQLite production app.

Pages:
  - Vendor Registration (public) - Smart Guided Registration
  - Management Login -> Management Dashboard (after auth)

Run:
  streamlit run app.py
"""

import os
import re
import sqlite3
from datetime import datetime

import pandas as pd
import streamlit as st

# --------------------------------------------------------------------------
# CONSTANTS / CONFIG
# --------------------------------------------------------------------------

DB_PATH = "vendors.db"
DOCS_DIR = "vendor_documents"

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "ikio@123"

os.makedirs(DOCS_DIR, exist_ok=True)

st.set_page_config(
    page_title="Vendor Registration Portal - IKIO",
    page_icon="🏭",
    layout="wide",
)

# --------------------------------------------------------------------------
# DATABASE LAYER
# --------------------------------------------------------------------------

def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def get_existing_columns(conn, table_name):
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table_name})")
    return [row[1] for row in cur.fetchall()]


# Base columns (already existed in production vendors.db before Phase 1)
BASE_COLUMNS = {
    "vendor_id": "TEXT",
    "company_name": "TEXT",
    "contact_person": "TEXT",
    "mobile": "TEXT",
    "email": "TEXT",
    "city": "TEXT",
    "state": "TEXT",
    "pan": "TEXT",
    "gst": "TEXT",
    "bank_name": "TEXT",
    "account_holder": "TEXT",
    "account_number": "TEXT",
    "ifsc_code": "TEXT",
    "documents": "TEXT",
    "created_at": "TEXT",
}

# New columns required for the official IKIO Vendor Registration Form
# (fields not already covered by a BASE_COLUMNS equivalent above)
PHASE1_NEW_COLUMNS = {
    "country": "TEXT",
    "address1": "TEXT",
    "address2": "TEXT",
    "address3": "TEXT",
    "pin_code": "TEXT",
    "payment_terms": "TEXT",
    "order_currency": "TEXT",
    "inco_terms": "TEXT",
    "telephone": "TEXT",
    "fax": "TEXT",
    "contact_person_finance": "TEXT",
    "email_finance": "TEXT",
    "tan": "TEXT",
    "msme_status": "TEXT",
    "msme_certificate": "TEXT",
    "nature_of_work": "TEXT",
    "vendor_sign_stamp": "TEXT",
    # Management-only approval fields (never shown/editable on the public
    # vendor form). Reserved here so the later management approval
    # workflow can read/write them without another migration.
    "initiated_by": "TEXT",
    "checked_by": "TEXT",
    "approved_by": "TEXT",
}

ALL_COLUMNS = {**BASE_COLUMNS, **PHASE1_NEW_COLUMNS}


def init_db():
    """
    Create the vendors table if it does not exist at all (fresh deployments).
    If the table already exists (your live vendors.db), NEVER recreate it.
    Instead, migrate it in place so all expected columns are present.
    """
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='vendors'"
    )
    table_exists = cur.fetchone() is not None

    if not table_exists:
        cols_sql = ",\n                ".join(
            f"{name} {ctype}" for name, ctype in ALL_COLUMNS.items()
        )
        cur.execute(
            f"""
            CREATE TABLE vendors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                {cols_sql}
            )
            """
        )
        conn.commit()
        conn.close()
        return

    # Table already exists (your live database) — migrate in place.
    existing_columns = get_existing_columns(conn, "vendors")
    for col_name, col_type in ALL_COLUMNS.items():
        if col_name not in existing_columns:
            cur.execute(f"ALTER TABLE vendors ADD COLUMN {col_name} {col_type}")
    conn.commit()

    # Backfill vendor_id for any existing rows that don't have one yet,
    # using the existing primary key `id`.
    cur.execute("SELECT id FROM vendors WHERE vendor_id IS NULL OR vendor_id = ''")
    rows_to_backfill = cur.fetchall()
    for (row_id,) in rows_to_backfill:
        cur.execute(
            "UPDATE vendors SET vendor_id = ? WHERE id = ?",
            (f"VR-{row_id:05d}", row_id),
        )
    conn.commit()
    conn.close()


def get_next_vendor_id():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT MAX(id) FROM vendors")
    max_id = cur.fetchone()[0]
    conn.close()
    return f"VR-{(max_id or 0) + 1:05d}"


def insert_vendor(data: dict):
    """Dynamic insert covering all known vendor columns present in `data`."""
    columns = list(data.keys())
    placeholders = ", ".join(["?"] * len(columns))
    col_sql = ", ".join(columns)
    values = [data[c] for c in columns]

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        f"INSERT INTO vendors ({col_sql}) VALUES ({placeholders})", values
    )
    conn.commit()
    conn.close()


def fetch_all_vendors() -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql_query("SELECT * FROM vendors ORDER BY id DESC", conn)
    conn.close()

    for col in ["vendor_id", "company_name", "city", "state", "created_at"]:
        if col not in df.columns:
            df[col] = ""

    df["vendor_id"] = df["vendor_id"].fillna("")
    empty_mask = df["vendor_id"] == ""
    if empty_mask.any():
        df.loc[empty_mask, "vendor_id"] = df.loc[empty_mask, "id"].apply(
            lambda x: f"VR-{int(x):05d}"
        )
    return df


def delete_vendor(row_id: int):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM vendors WHERE id = ?", (row_id,))
    conn.commit()
    conn.close()


init_db()

# --------------------------------------------------------------------------
# SESSION STATE INITIALIZATION
# --------------------------------------------------------------------------

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "username" not in st.session_state:
    st.session_state.username = None
if "login_error" not in st.session_state:
    st.session_state.login_error = False
if "confirm_delete_id" not in st.session_state:
    st.session_state.confirm_delete_id = None

# Registration form field keys (widgets write directly into these session
# state keys so the completion meter can update live on every rerun).
FORM_KEYS = [
    "company_name", "country", "region_state", "address1", "address2", "address3",
    "city", "pin_code", "payment_terms", "order_currency", "inco_terms",
    "telephone", "mobile", "fax", "contact_sales", "email_sales",
    "contact_finance", "email_finance", "pan", "tan", "gstin",
    "beneficiary_name", "bank_address", "bank_account_no", "bank_ifsc",
    "msme_status", "nature_of_work",
]
for k in FORM_KEYS:
    if k not in st.session_state:
        st.session_state[k] = "" if k != "msme_status" else "No"
if "msme_certificate_file" not in st.session_state:
    st.session_state.msme_certificate_file = None
if "vendor_sign_stamp_file" not in st.session_state:
    st.session_state.vendor_sign_stamp_file = None
if "reg_submitted_id" not in st.session_state:
    st.session_state.reg_submitted_id = None


def do_logout():
    st.session_state.logged_in = False
    st.session_state.username = None
    st.session_state.login_error = False
    st.session_state.confirm_delete_id = None
    st.rerun()


def reset_registration_form():
    for k in FORM_KEYS:
        st.session_state[k] = "" if k != "msme_status" else "No"
    st.session_state.reg_submitted_id = None


# --------------------------------------------------------------------------
# VALIDATION HELPERS
# --------------------------------------------------------------------------

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MOBILE_RE = re.compile(r"^[6-9]\d{9}$")
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
GST_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$")
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")


# --------------------------------------------------------------------------
# COMPLETION TRACKING (Smart Guided Registration)
# --------------------------------------------------------------------------

def section1_required_filled():
    s = st.session_state
    checks = [s.company_name, s.country, s.region_state, s.address1, s.city, s.pin_code]
    return all(str(v).strip() for v in checks)


def section2_required_filled():
    s = st.session_state
    checks = [s.payment_terms, s.order_currency, s.inco_terms]
    return all(str(v).strip() for v in checks)


def section3_required_filled():
    s = st.session_state
    checks = [s.mobile, s.contact_sales, s.email_sales, s.contact_finance, s.email_finance]
    return all(str(v).strip() for v in checks)


def section4_required_filled():
    s = st.session_state
    checks = [
        s.pan, s.gstin, s.beneficiary_name, s.bank_address,
        s.bank_account_no, s.bank_ifsc, s.nature_of_work,
    ]
    ok = all(str(v).strip() for v in checks)
    if s.msme_status == "Yes":
        ok = ok and st.session_state.msme_certificate_file is not None
    return ok


def section5_required_filled():
    return st.session_state.vendor_sign_stamp_file is not None


def overall_completion_percent():
    section_fns = [
        (section1_required_filled, 6),
        (section2_required_filled, 3),
        (section3_required_filled, 5),
        (section4_required_filled, 7 + (1 if st.session_state.msme_status == "Yes" else 0)),
        (section5_required_filled, 1),
    ]
    total_weight = sum(w for _, w in section_fns)
    done_weight = sum(w for fn, w in section_fns if fn())
    return int(round(done_weight / total_weight * 100))


def section_header(title, is_complete):
    if is_complete:
        st.markdown(f"### ✅ {title}")
    else:
        st.markdown(f"### {title}")


# --------------------------------------------------------------------------
# PAGE: VENDOR REGISTRATION (PUBLIC) — Smart Guided Registration
# --------------------------------------------------------------------------

def page_vendor_registration():
    st.title("🏭 Vendor Registration")
    st.caption("IKIO Solutions Private Limited — New Vendor Onboarding")

    if st.session_state.reg_submitted_id:
        st.success("✅ Registration submitted successfully!")
        st.info(f"Your Vendor Registration ID is: **{st.session_state.reg_submitted_id}**")
        st.caption("Please save this ID for future reference.")
        if st.button("Register Another Vendor"):
            reset_registration_form()
            st.rerun()
        return

    pct = overall_completion_percent()
    st.markdown(f"**Registration Completion: {pct}%**")
    st.progress(pct / 100)
    st.caption("Fields marked with * are required. This form saves nothing until you submit at the end.")
    st.divider()

    s = st.session_state

    # ---------------- Section 1: Company Information ----------------
    section_header("Company Information", section1_required_filled())
    with st.container(border=True):
        s.company_name = st.text_input(
            "Company Name *", value=s.company_name,
            placeholder="e.g. ABC Electronics Pvt. Ltd.",
        )
        c1, c2 = st.columns(2)
        with c1:
            s.country = st.text_input("Country *", value=s.country, placeholder="e.g. India")
        with c2:
            s.region_state = st.text_input(
                "Region / State *", value=s.region_state, placeholder="e.g. Uttar Pradesh"
            )
        s.address1 = st.text_input("Address 1 *", value=s.address1, placeholder="e.g. Plot No. 12, Industrial Area")
        s.address2 = st.text_input("Address 2", value=s.address2, placeholder="(optional)")
        s.address3 = st.text_input("Address 3", value=s.address3, placeholder="(optional)")
        c3, c4 = st.columns(2)
        with c3:
            s.city = st.text_input("City *", value=s.city, placeholder="e.g. Noida")
        with c4:
            s.pin_code = st.text_input("PIN Code *", value=s.pin_code, placeholder="e.g. 201301", max_chars=10)

    # ---------------- Section 2: Business Terms ----------------
    section_header("Business Terms", section2_required_filled())
    with st.container(border=True):
        s.payment_terms = st.text_input(
            "Payment Terms *", value=s.payment_terms, placeholder="e.g. Net 30 Days"
        )
        s.order_currency = st.text_input(
            "Order Currency *", value=s.order_currency, placeholder="e.g. INR / USD"
        )
        s.inco_terms = st.text_input(
            "INCO Terms (Shipping Terms) *", value=s.inco_terms, placeholder="e.g. FOB, EXW, CIF"
        )

    # ---------------- Section 3: Contact Information ----------------
    section_header("Contact Information", section3_required_filled())
    with st.container(border=True):
        c1, c2 = st.columns(2)
        with c1:
            s.telephone = st.text_input("Telephone", value=s.telephone, placeholder="(optional)")
        with c2:
            s.mobile = st.text_input(
                "Mobile No. *", value=s.mobile, placeholder="e.g. 9876543210", max_chars=10
            )
        s.fax = st.text_input("FAX No.", value=s.fax, placeholder="(optional)")
        st.markdown("**Sales Contact**")
        c3, c4 = st.columns(2)
        with c3:
            s.contact_sales = st.text_input(
                "Contact Person — Sales *", value=s.contact_sales, placeholder="e.g. Rahul Sharma"
            )
        with c4:
            s.email_sales = st.text_input(
                "E-Mail ID — Sales *", value=s.email_sales, placeholder="e.g. sales@company.com"
            )
        st.markdown("**Finance & Accounts Contact**")
        c5, c6 = st.columns(2)
        with c5:
            s.contact_finance = st.text_input(
                "Contact Person — Finance & Accounts *", value=s.contact_finance,
                placeholder="e.g. Priya Verma",
            )
        with c6:
            s.email_finance = st.text_input(
                "E-Mail ID — Finance & Accounts *", value=s.email_finance,
                placeholder="e.g. accounts@company.com",
            )

    # ---------------- Section 4: Tax & Bank Details ----------------
    section_header("Tax & Bank Details", section4_required_filled())
    with st.container(border=True):
        c1, c2 = st.columns(2)
        with c1:
            s.pan = st.text_input(
                "PAN *", value=s.pan, placeholder="e.g. ABCDE1234F", max_chars=10
            ).upper()
        with c2:
            s.tan = st.text_input("TAN", value=s.tan, placeholder="(optional)", max_chars=10).upper()
        s.gstin = st.text_input(
            "GSTIN *", value=s.gstin, placeholder="e.g. 09ABCDE1234F1Z5", max_chars=15
        ).upper()

        st.markdown("**Bank Details**")
        s.beneficiary_name = st.text_input(
            "Beneficiary Name (Name on Bank Account) *", value=s.beneficiary_name,
            placeholder="e.g. ABC Electronics Pvt. Ltd.",
        )
        s.bank_address = st.text_input(
            "Bank Name & Address *", value=s.bank_address,
            placeholder="e.g. HDFC Bank, Sector 18, Noida",
        )
        c3, c4 = st.columns(2)
        with c3:
            s.bank_account_no = st.text_input(
                "Bank A/C No. (Bank Account Number) *", value=s.bank_account_no,
                placeholder="e.g. 001234567890",
            )
        with c4:
            s.bank_ifsc = st.text_input(
                "Bank IFSC Code *", value=s.bank_ifsc, placeholder="e.g. HDFC0001234", max_chars=11
            ).upper()

        st.markdown("**MSME Status**")
        s.msme_status = st.radio(
            "Whether party covered under Micro Small and Medium Enterprise Development Act (MSMED) *",
            ["No", "Yes"],
            index=["No", "Yes"].index(s.msme_status) if s.msme_status in ["No", "Yes"] else 0,
            horizontal=True,
        )
        if s.msme_status == "Yes":
            msme_file = st.file_uploader(
                "MSME Certificate * (required since you selected Yes)",
                type=["pdf", "jpg", "jpeg", "png"],
                key="msme_certificate_uploader",
            )
            if msme_file is not None:
                st.session_state.msme_certificate_file = msme_file
                st.success("✓ MSME Certificate uploaded")
        else:
            st.session_state.msme_certificate_file = None

        s.nature_of_work = st.text_input(
            "Nature of Work (What do you supply?) *", value=s.nature_of_work,
            placeholder="e.g. LED Driver Components",
        )

    # ---------------- Section 5: Documents & Final Submission ----------------
    section_header("Documents & Final Submission", section5_required_filled())
    with st.container(border=True):
        st.markdown("**Document Checklist**")
        if st.session_state.msme_status == "Yes":
            if st.session_state.msme_certificate_file is not None:
                st.markdown("✓ MSME Certificate — uploaded")
            else:
                st.markdown("◻ MSME Certificate — required (selected MSME: Yes above)")

        sign_file = st.file_uploader(
            "Vendor Sign & Stamp * (upload a signed and stamped document/image — mandatory)",
            type=["pdf", "jpg", "jpeg", "png"],
            key="vendor_sign_stamp_uploader",
        )
        if sign_file is not None:
            st.session_state.vendor_sign_stamp_file = sign_file
            st.success("✓ Vendor Sign & Stamp uploaded")
        else:
            st.markdown("◻ Vendor Sign & Stamp — required")

        st.divider()
        submitted = st.button("Submit Registration", use_container_width=True, type="primary")

    if submitted:
        errors = []

        required_text_fields = {
            "Company Name": s.company_name,
            "Country": s.country,
            "Region / State": s.region_state,
            "Address 1": s.address1,
            "City": s.city,
            "PIN Code": s.pin_code,
            "Payment Terms": s.payment_terms,
            "Order Currency": s.order_currency,
            "INCO Terms": s.inco_terms,
            "Mobile No.": s.mobile,
            "Contact Person — Sales": s.contact_sales,
            "E-Mail ID — Sales": s.email_sales,
            "Contact Person — Finance & Accounts": s.contact_finance,
            "E-Mail ID — Finance & Accounts": s.email_finance,
            "PAN": s.pan,
            "GSTIN": s.gstin,
            "Beneficiary Name": s.beneficiary_name,
            "Bank Name & Address": s.bank_address,
            "Bank A/C No.": s.bank_account_no,
            "Bank IFSC Code": s.bank_ifsc,
            "Nature of Work": s.nature_of_work,
        }
        for label, value in required_text_fields.items():
            if not value or not str(value).strip():
                errors.append(f"{label} is required.")

        if s.mobile and not MOBILE_RE.match(s.mobile.strip()):
            errors.append("Please enter a valid 10-digit mobile number.")
        if s.email_sales and not EMAIL_RE.match(s.email_sales.strip()):
            errors.append("Sales email address is not valid.")
        if s.email_finance and not EMAIL_RE.match(s.email_finance.strip()):
            errors.append("Finance & Accounts email address is not valid.")
        if s.pan and not PAN_RE.match(s.pan.strip()):
            errors.append("PAN format looks incorrect (example: ABCDE1234F).")
        if s.gstin and not GST_RE.match(s.gstin.strip()):
            errors.append("GSTIN format looks incorrect.")
        if s.bank_ifsc and not IFSC_RE.match(s.bank_ifsc.strip()):
            errors.append("Bank IFSC Code format looks incorrect (example: HDFC0001234).")

        if s.msme_status == "Yes" and st.session_state.msme_certificate_file is None:
            errors.append("MSME Certificate is required since you selected 'Yes' for MSME status.")
        if st.session_state.vendor_sign_stamp_file is None:
            errors.append("Vendor Sign & Stamp document is required.")

        if errors:
            for e in errors:
                st.error(e)
        else:
            vendor_id = get_next_vendor_id()
            vendor_folder = os.path.join(DOCS_DIR, vendor_id)
            os.makedirs(vendor_folder, exist_ok=True)

            saved_filenames = []
            msme_cert_name = ""
            if st.session_state.msme_certificate_file is not None:
                f = st.session_state.msme_certificate_file
                path = os.path.join(vendor_folder, f.name)
                with open(path, "wb") as out:
                    out.write(f.getbuffer())
                saved_filenames.append(f.name)
                msme_cert_name = f.name

            sign_file_obj = st.session_state.vendor_sign_stamp_file
            path = os.path.join(vendor_folder, sign_file_obj.name)
            with open(path, "wb") as out:
                out.write(sign_file_obj.getbuffer())
            saved_filenames.append(sign_file_obj.name)
            sign_stamp_name = sign_file_obj.name

            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            record = {
                "vendor_id": vendor_id,
                "company_name": s.company_name.strip(),
                "contact_person": s.contact_sales.strip(),
                "mobile": s.mobile.strip(),
                "email": s.email_sales.strip(),
                "city": s.city.strip(),
                "state": s.region_state.strip(),
                "pan": s.pan.strip(),
                "gst": s.gstin.strip(),
                "bank_name": s.bank_address.strip(),
                "account_holder": s.beneficiary_name.strip(),
                "account_number": s.bank_account_no.strip(),
                "ifsc_code": s.bank_ifsc.strip(),
                "documents": ", ".join(saved_filenames),
                "created_at": now_str,
                "country": s.country.strip(),
                "address1": s.address1.strip(),
                "address2": s.address2.strip(),
                "address3": s.address3.strip(),
                "pin_code": s.pin_code.strip(),
                "payment_terms": s.payment_terms.strip(),
                "order_currency": s.order_currency.strip(),
                "inco_terms": s.inco_terms.strip(),
                "telephone": s.telephone.strip(),
                "fax": s.fax.strip(),
                "contact_person_finance": s.contact_finance.strip(),
                "email_finance": s.email_finance.strip(),
                "tan": s.tan.strip(),
                "msme_status": s.msme_status,
                "msme_certificate": msme_cert_name,
                "nature_of_work": s.nature_of_work.strip(),
                "vendor_sign_stamp": sign_stamp_name,
                # Management-only fields — always blank from the public form.
                "initiated_by": "",
                "checked_by": "",
                "approved_by": "",
            }

            insert_vendor(record)
            st.session_state.reg_submitted_id = vendor_id
            st.rerun()


# --------------------------------------------------------------------------
# PAGE: MANAGEMENT LOGIN
# --------------------------------------------------------------------------

def page_management_login():
    st.title("🔐 Management Login")
    st.divider()

    with st.form("management_login_form"):
        username_input = st.text_input("Username")
        password_input = st.text_input("Password", type="password")
        login_clicked = st.form_submit_button("Login", use_container_width=True)

    if login_clicked:
        if username_input.strip() == ADMIN_USERNAME and password_input == ADMIN_PASSWORD:
            st.session_state.logged_in = True
            st.session_state.username = username_input.strip()
            st.session_state.login_error = False
            st.rerun()
        else:
            st.session_state.logged_in = False
            st.session_state.username = None
            st.session_state.login_error = True

    if st.session_state.login_error:
        st.error("Invalid Username or Password")


# --------------------------------------------------------------------------
# PAGE: MANAGEMENT DASHBOARD (PROTECTED) — unchanged from previous phase
# --------------------------------------------------------------------------

def page_management_dashboard():
    st.title("📊 Management Dashboard")
    st.caption(f"Logged in as **{st.session_state.username}**")
    st.divider()

    df = fetch_all_vendors()

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Vendors", len(df))
    with col2:
        latest_id = df.iloc[0]["vendor_id"] if not df.empty else "—"
        st.metric("Latest Vendor ID", latest_id)
    with col3:
        today_str = datetime.now().strftime("%Y-%m-%d")
        today_count = (
            df[df["created_at"].astype(str).str.startswith(today_str)].shape[0]
            if not df.empty
            else 0
        )
        st.metric("Registrations Today", today_count)

    st.divider()
    st.markdown("#### All Registered Vendors")

    if df.empty:
        st.info("No vendors registered yet.")
        return

    search = st.text_input("Search by company name, vendor ID, city, or state")
    display_df = df.copy()
    if search:
        mask = (
            display_df["company_name"].astype(str).str.contains(search, case=False, na=False)
            | display_df["vendor_id"].astype(str).str.contains(search, case=False, na=False)
            | display_df["city"].astype(str).str.contains(search, case=False, na=False)
            | display_df["state"].astype(str).str.contains(search, case=False, na=False)
        )
        display_df = display_df[mask]

    st.dataframe(display_df, use_container_width=True, hide_index=True)

    csv_data = display_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download as CSV",
        data=csv_data,
        file_name=f"vendors_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
    )

    st.divider()
    st.markdown("#### Manage / Delete Vendors")
    st.caption("Management only. This permanently removes the vendor record from the database.")

    for _, row in display_df.iterrows():
        row_id = int(row["id"])
        vendor_label = f"{row['vendor_id']} — {row['company_name']}"

        with st.container(border=True):
            c1, c2 = st.columns([5, 1])
            with c1:
                st.markdown(f"**{vendor_label}**")
                st.caption(
                    f"{row.get('city', '')}, {row.get('state', '')} · Registered: {row.get('created_at', '')}"
                )
            with c2:
                if st.session_state.confirm_delete_id != row_id:
                    if st.button("Delete", key=f"delete_btn_{row_id}", use_container_width=True):
                        st.session_state.confirm_delete_id = row_id
                        st.rerun()

            if st.session_state.confirm_delete_id == row_id:
                st.warning(f"Are you sure you want to permanently delete **{vendor_label}**?")
                confirm_col1, confirm_col2 = st.columns(2)
                with confirm_col1:
                    if st.button(
                        "Yes, Delete",
                        key=f"confirm_delete_{row_id}",
                        use_container_width=True,
                        type="primary",
                    ):
                        delete_vendor(row_id)
                        st.session_state.confirm_delete_id = None
                        st.success(f"Vendor {vendor_label} deleted.")
                        st.rerun()
                with confirm_col2:
                    if st.button(
                        "Cancel",
                        key=f"cancel_delete_{row_id}",
                        use_container_width=True,
                    ):
                        st.session_state.confirm_delete_id = None
                        st.rerun()


# --------------------------------------------------------------------------
# SIDEBAR NAVIGATION (auth-aware)
# --------------------------------------------------------------------------

st.sidebar.title("Select Page")

if not st.session_state.logged_in:
    page = st.sidebar.radio(
        "Navigation",
        ["Vendor Registration", "Management Login"],
        label_visibility="collapsed",
    )
else:
    st.sidebar.success(f"Logged in as {st.session_state.username}")
    page = st.sidebar.radio(
        "Navigation",
        ["Vendor Registration", "Management Dashboard"],
        label_visibility="collapsed",
    )
    st.sidebar.divider()
    if st.sidebar.button("Logout", use_container_width=True):
        do_logout()

# --------------------------------------------------------------------------
# ROUTER
# --------------------------------------------------------------------------

if page == "Vendor Registration":
    page_vendor_registration()
elif page == "Management Login" and not st.session_state.logged_in:
    page_management_login()
elif page == "Management Dashboard" and st.session_state.logged_in:
    page_management_dashboard()
else:
    page_management_login()
