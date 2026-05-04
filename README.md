# PharmaSight ERP

**PharmaSight** is a full-stack pharmacy ERP system built to manage **inventory, sales (POS), procurement, and financial workflows** for retail and multi-branch pharmacies.

It is designed with a strong focus on **inventory intelligence**, treating stock as a **first-class ledger** with batch tracking, expiry awareness (FEFO), and cost-driven decision logic.

---

## 🚀 Developer Highlights

- Built a full-stack ERP system using **FastAPI (Python)**, **PostgreSQL**, and **vanilla JavaScript**
- Designed a **stock-ledger architecture** with append-only inventory movements
- Implemented **batch tracking and FEFO allocation logic**
- Developed backend workflows for:
  - Inventory management  
  - Procurement and GRN processing  
  - Pricing and margin control  
- Structured system for **multi-branch scalability**
- Built automation-ready backend logic for future AI integration

---

## 🤖 AI / Intelligent Features (In Progress)

- Inventory analytics engine for:
  - Demand pattern analysis  
  - Stock recommendations  
- Procurement automation logic for decision support  
- Exploring **chatbot interface** for querying inventory and sales insights  
- Ongoing work toward **AI-assisted inventory optimization**

---

## 🎯 Key Features

| Area | Capabilities |
|------|-------------|
| **Inventory** | Batch tracking, FEFO, stock ledger, stock take |
| **Sales (POS)** | Checkout, pricing, margin-aware selling |
| **Purchases** | Supplier linkage, GRN workflows |
| **Finance** | Cashbook, expenses, reporting |
| **Multi-branch** | Company-scoped operations across branches |
| **Compliance** | VAT handling, Kenya-oriented invoicing, eTIMS-ready backend |

---

## 🧱 Architecture

- **Backend:** FastAPI (Python)
- **Database:** PostgreSQL (via Supabase)
- **Frontend:** Vanilla JavaScript (SPA-style)
- **Auth:** Supabase authentication

---

## 🧠 Core Design Principles

- **Inventory-first system** — every stock change is traceable  
- **Base unit storage** — accurate stock accounting  
- **Breaking bulk** — pack-to-unit conversion  
- **FEFO** — expiry-aware stock allocation  
- **Cost-aware pricing** — margin-driven decisions  
- **Auditability** — structured and traceable operations  

---

## ⚙️ Quick Start (Local Development)

From the `pharmasight` folder:

### Windows
```bash
start.bat
# OR
.\start.ps1
# OR
python start.py
