import sqlite3
import datetime
import streamlit as st
import pandas as pd

# -------------------- DATABASE --------------------
conn = sqlite3.connect("vendors.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS vendors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT,
    contact_person TEXT,
    mobile TEXT,
    email TEXT,
    address TEXT,
    city TEXT,
    state TEXT,
    pin_code TEXT,
    pan TEXT,
    gstin TEXT,
    msme TEXT,
    category TEXT,
    products TEXT,
    bank_name TEXT,
    account_holder TEXT,
    account_number TEXT,
    ifsc TEXT,
    submitted_on TEXT
)
""")

conn.commit()

# -------------------- PAGE SETTINGS --------------------
st.set_page_config(
    page_title="Vendor Registration Portal",
    page_icon="🏭",
    layout="wide"
)

# -------------------- SIDEBAR --------------------
page = st.sidebar.radio(
    "Select Page",
    ["Vendor Registration", "Management Dashboard"]
)

# ======================================================
# VENDOR REGISTRATION PAGE
# ======================================================
if page == "Vendor Registration":

    st.title("🏭 IKIO Vendor Registration Portal")
    st.write("Please fill in the vendor registration form below.")

    st.header("Vendor / Company Details")

    col1, col2 = st.columns(2)

    with col1:
        company_name = st.text_input("Company / Vendor Name *")
    with col2:
        contact_person = st.text_input("Contact Person Name *")

    col1, col2 = st.columns(2)

    with col1:
        mobile = st.text_input("Mobile Number *")
    with col2:
        email = st.text_input("Email ID *")

    address = st.text_area("Complete Address *", height=90)

    col1, col2 = st.columns(2)

    with col1:
        city = st.text_input("City *")
    with col2:
        state = st.text_input("State *")

    pin_code = st.text_input("PIN Code *")

    st.divider()

    st.header("Tax & Registration Details")

    col1, col2 = st.columns(2)

    with col1:
        pan = st.text_input("PAN Number *")
    with col2:
        gstin = st.text_input("GSTIN *")

    msme = st.text_input("MSME / Udyam Registration No.")

    st.divider()

    st.header("Products / Services")

    col1, col2 = st.columns(2)

    with col1:
        category = st.selectbox(
            "Vendor Category",
            [
                "Raw Material",
                "Components",
                "Packaging",
                "Service Provider",
                "Other"
            ]
        )

    products = st.text_area(
        "Products / Materials / Services Offered *",
        height=90
    )

    st.divider()

    st.header("Bank Details")

    col1, col2 = st.columns(2)

    with col1:
        bank_name = st.text_input("Bank Name *")
    with col2:
        account_holder = st.text_input("Account Holder Name *")

    col1, col2 = st.columns(2)

    with col1:
        account_number = st.text_input("Account Number *")
    with col2:
        ifsc = st.text_input("IFSC Code *")

    st.divider()

    st.header("Documents")

    col1, col2 = st.columns(2)

    with col1:
        st.file_uploader(
            "Upload PAN Card",
            type=["pdf", "jpg", "jpeg", "png"]
        )

    with col2:
        st.file_uploader(
            "Upload GST Certificate",
            type=["pdf", "jpg", "jpeg", "png"]
        )

    st.file_uploader(
        "Upload Cancelled Cheque / Bank Proof",
        type=["pdf", "jpg", "jpeg", "png"]
    )

    st.divider()

    declaration = st.checkbox(
        "I confirm that the information provided above is true and correct."
    )

    if st.button("Submit Vendor Registration", use_container_width=True):

        if not company_name or not contact_person or not mobile or not email:
            st.error("Please fill all mandatory fields.")

        elif not declaration:
            st.error("Please accept the declaration before submitting.")

        else:

            submitted_on = datetime.datetime.now().strftime("%d-%m-%Y %H:%M")

            cursor.execute("""
            INSERT INTO vendors (
                company_name,
                contact_person,
                mobile,
                email,
                address,
                city,
                state,
                pin_code,
                pan,
                gstin,
                msme,
                category,
                products,
                bank_name,
                account_holder,
                account_number,
                ifsc,
                submitted_on
            )
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                company_name,
                contact_person,
                mobile,
                email,
                address,
                city,
                state,
                pin_code,
                pan,
                gstin,
                msme,
                category,
                products,
                bank_name,
                account_holder,
                account_number,
                ifsc,
                submitted_on
            ))

            conn.commit()

            vendor_id = cursor.lastrowid

            st.success("Vendor Registration Submitted Successfully!")
            st.info(f"Vendor Registration ID: VR-{vendor_id:05d}")

# ======================================================
# MANAGEMENT DASHBOARD
# ======================================================
else:

    st.title("📊 Management Dashboard")

    df = pd.read_sql_query(
        "SELECT * FROM vendors ORDER BY id DESC",
        conn
    )

    col1, col2 = st.columns(2)

    with col1:
        st.metric("Total Vendors", len(df))

    with col2:
        if len(df) > 0:
            st.metric("Latest Vendor ID", f"VR-{int(df.iloc[0]['id']):05d}")
        else:
            st.metric("Latest Vendor ID", "-")

    st.subheader("Registered Vendors")

    st.dataframe(
        df,
        use_container_width=True,
        hide_index=True
    )
