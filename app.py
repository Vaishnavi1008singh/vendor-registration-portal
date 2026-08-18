"""
IKIO Vendor Registration Portal
--------------------------------
Streamlit + SQLite production app.

Pages:
  - Vendor Registration (public)
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
    """Create a new SQLite connection (thread-safe for Streamlit reruns)."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def get_existing_columns(conn, table_name):
    cur = conn.cursor()
    cur.execute(f"PRAGMA table_info({table_name})")
    return [row[1] for row in cur.fetchall()]


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
        cur.execute(
            """
            CREATE TABLE vendors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor_id TEXT UNIQUE,
                company_name TEXT,
                contact_person TEXT,
                mobile TEXT,
                email TEXT,
                city TEXT,
                state TEXT,
                pan TEXT,
                gst TEXT,
                bank_name TEXT,
                account_holder TEXT,
                account_number TEXT,
                ifsc_code TEXT,
                documents TEXT,
                created_at TEXT
            )
            """
        )
        conn.commit()
        conn.close()
        return

    # Table already exists (your live database) — migrate in place.
    existing_columns = get_existing_columns(conn, "vendors")

    required_columns = {
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

    for col_name, col_type in required_columns.items():
        if col_name not in existing_columns:
            cur.execute(f"ALTER TABLE vendors ADD COLUMN {col_name} {col_type}")

    conn.commit()

    # Backfill vendor_id for any existing rows that don't have one yet,
    # using the existing primary key `id` so old records get a stable,
    # correctly formatted Vendor Registration ID (e.g. VR-00001).
    cur.execute("SELECT id FROM vendors WHERE vendor_id IS NULL OR vendor_id = ''")
    rows_to_backfill = cur.fetchall()
    for (row_id,) in rows_to_backfill:
        formatted_id = f"VR-{row_id:05d}"
        cur.execute(
            "UPDATE vendors SET vendor_id = ? WHERE id = ?",
            (formatted_id, row_id),
        )

    conn.commit()
    conn.close()


def get_next_vendor_id():
    """Generate the next sequential vendor id like VR-00001, based on id."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT MAX(id) FROM vendors")
    max_id = cur.fetchone()[0]
    conn.close()
    next_id = (max_id or 0) + 1
    return f"VR-{next_id:05d}"


def insert_vendor(data: dict):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO vendors (
            vendor_id, company_name, contact_person, mobile, email,
            city, state, pan, gst, bank_name, account_holder,
            account_number, ifsc_code, documents, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data["vendor_id"],
            data["company_name"],
            data["contact_person"],
            data["mobile"],
            data["email"],
            data["city"],
            data["state"],
            data["pan"],
            data["gst"],
            data["bank_name"],
            data["account_holder"],
            data["account_number"],
            data["ifsc_code"],
            data["documents"],
            data["created_at"],
        ),
    )
    conn.commit()
    conn.close()


def fetch_all_vendors() -> pd.DataFrame:
    conn = get_connection()
    df = pd.read_sql_query("SELECT * FROM vendors ORDER BY id DESC", conn)
    conn.close()

    # Safety net: even after migration, guarantee the columns the UI relies
    # on always exist in the DataFrame, so the dashboard can never crash
    # with a KeyError again even if the schema is unusual.
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
# SESSION STATE INITIALIZATION (single source of truth for auth)
# --------------------------------------------------------------------------

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if "username" not in st.session_state:
    st.session_state.username = None

if "login_error" not in st.session_state:
    st.session_state.login_error = False

if "confirm_delete_id" not in st.session_state:
    st.session_state.confirm_delete_id = None


def do_logout():
    """Fully reset auth-related session state, then rerun."""
    st.session_state.logged_in = False
    st.session_state.username = None
    st.session_state.login_error = False
    st.session_state.confirm_delete_id = None
    st.rerun()


# --------------------------------------------------------------------------
# VALIDATION HELPERS
# --------------------------------------------------------------------------

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MOBILE_RE = re.compile(r"^[6-9]\d{9}$")
PAN_RE = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
GST_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$")
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")


# --------------------------------------------------------------------------
# PAGE: VENDOR REGISTRATION (PUBLIC)
# --------------------------------------------------------------------------

def page_vendor_registration():
    st.title("🏭 Vendor Registration")
    st.caption("IKIO — New Vendor Onboarding Form")
    st.divider()

    with st.form("vendor_registration_form", clear_on_submit=True):
        col1, col2 = st.columns(2)

        with col1:
            company_name = st.text_input("Company Name *")
            mobile = st.text_input("Mobile Number *", max_chars=10)
            city = st.text_input("City *")
            pan = st.text_input("PAN Number *", max_chars=10).upper()
            bank_name = st.text_input("Bank Name *")
            account_number = st.text_input("Account Number *")

        with col2:
            contact_person = st.text_input("Contact Person *")
            email = st.text_input("Email Address *")
            state = st.text_input("State *")
            gst = st.text_input("GST Number *", max_chars=15).upper()
            account_holder = st.text_input("Account Holder Name *")
            ifsc_code = st.text_input("IFSC Code *", max_chars=11).upper()

        st.markdown("#### Document Upload")
        uploaded_files = st.file_uploader(
            "Upload supporting documents (PAN card, GST certificate, cancelled cheque, etc.)",
            accept_multiple_files=True,
            type=["pdf", "png", "jpg", "jpeg"],
        )

        submitted = st.form_submit_button("Submit Registration", use_container_width=True)

    if submitted:
        errors = []

        required_fields = {
            "Company Name": company_name,
            "Contact Person": contact_person,
            "Mobile Number": mobile,
            "Email Address": email,
            "City": city,
            "State": state,
            "PAN Number": pan,
            "GST Number": gst,
            "Bank Name": bank_name,
            "Account Holder Name": account_holder,
            "Account Number": account_number,
            "IFSC Code": ifsc_code,
        }
        for label, value in required_fields.items():
            if not value or not value.strip():
                errors.append(f"{label} is required.")

        if mobile and not MOBILE_RE.match(mobile.strip()):
            errors.append("Mobile number must be a valid 10-digit Indian number.")
        if email and not EMAIL_RE.match(email.strip()):
            errors.append("Email address is not valid.")
        if pan and not PAN_RE.match(pan.strip()):
            errors.append("PAN number format is invalid (e.g. ABCDE1234F).")
        if gst and not GST_RE.match(gst.strip()):
            errors.append("GST number format is invalid.")
        if ifsc_code and not IFSC_RE.match(ifsc_code.strip()):
            errors.append("IFSC code format is invalid (e.g. HDFC0001234).")

        if errors:
            for e in errors:
                st.error(e)
        else:
            vendor_id = get_next_vendor_id()
            saved_filenames = []

            if uploaded_files:
                vendor_folder = os.path.join(DOCS_DIR, vendor_id)
                os.makedirs(vendor_folder, exist_ok=True)
                for f in uploaded_files:
                    file_path = os.path.join(vendor_folder, f.name)
                    with open(file_path, "wb") as out:
                        out.write(f.getbuffer())
                    saved_filenames.append(f.name)

            record = {
                "vendor_id": vendor_id,
                "company_name": company_name.strip(),
                "contact_person": contact_person.strip(),
                "mobile": mobile.strip(),
                "email": email.strip(),
                "city": city.strip(),
                "state": state.strip(),
                "pan": pan.strip(),
                "gst": gst.strip(),
                "bank_name": bank_name.strip(),
                "account_holder": account_holder.strip(),
                "account_number": account_number.strip(),
                "ifsc_code": ifsc_code.strip(),
                "documents": ", ".join(saved_filenames) if saved_filenames else "",
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }

            insert_vendor(record)

            st.success("✅ Registration submitted successfully!")
            st.info(f"Your Vendor Registration ID is: **{vendor_id}**")
            st.caption("Please save this ID for future reference.")


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
# PAGE: MANAGEMENT DASHBOARD (PROTECTED)
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
    # Safety net: if somehow a protected page is reached without auth,
    # bounce back to the login page instead of showing an error.
    page_management_login()
