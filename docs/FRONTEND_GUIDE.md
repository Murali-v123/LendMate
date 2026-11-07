# LendMate · Frontend Guide

This guide explains how the presentation layer of LendMate is structured and where to make frontend modifications.

---

## Directory Location

All frontend files are located in the `frontend/` directory at the project root:

```
frontend/
├── templates/
│   ├── accounts/
│   ├── core/
│   ├── layouts/
│   ├── lending/
│   ├── notifications/
│   ├── partials/
│   └── registration/
└── static/
    ├── css/
    ├── js/
    ├── img/
    └── favicon/
```

---

## Where to Make Common UI Changes

| What you want to change | Which file to edit |
| :--- | :--- |
| **Color palette, fonts, spacing, badges, cards** | `frontend/static/css/lendmate.css` |
| **Overall application frame & navigation** | `frontend/templates/layouts/app.html` |
| **Main navigation menu items** | `frontend/templates/partials/nav_links.html` |
| **Browser tab title, fonts & meta tags** | `frontend/templates/layouts/base.html` |
| **Lender Dashboard UI (metric cards, recent tables)** | `frontend/templates/core/dashboard.html` |
| **Lender Settings page & WhatsApp preferences UI** | `frontend/templates/core/settings.html` |
| **Borrower Profile (loans, trackers, summary)** | `frontend/templates/lending/borrower_detail.html` |
| **Borrower Directory table** | `frontend/templates/lending/borrower_list.html` |
| **Add Borrower form page** | `frontend/templates/lending/add_borrower.html` |
| **Add Loan form page** | `frontend/templates/lending/add_loan.html` |
| **Loan Details page** | `frontend/templates/lending/loan_detail.html` |
| **Record Payment form page** | `frontend/templates/lending/add_payment.html` |
| **WhatsApp Notification History table & filters** | `frontend/templates/notifications/history.html` |
| **Login screen** | `frontend/templates/accounts/login.html` |
| **LendMate brand logo or mark** | `frontend/static/img/lendmate-mark.svg` |
| **Favicon** | `frontend/static/img/favicon.svg` and `frontend/static/favicon/favicon.svg` |

---

## Design System Guidelines

LendMate employs a **warm luxury / editorial design system**:
- **Colors**:
  - Background: `#F4EFE6` (warm ivory)
  - Secondary background: `#EAE1D4`
  - Surface: `#FFFDF8`
  - Text: `#342820` (dark walnut)
  - Muted: `#817366`
  - Accent / Primary: `#A85F45` (terracotta)
  - Success: `#66816B`
  - Warning: `#C28B48`
  - Danger: `#AC5147`
- **Typography**:
  - Serif Display: *Playfair Display*, *Cormorant Garamond*, Georgia
  - Sans Body: *Inter*, *DM Sans*, system-ui
- **Status Pills**:
  - `lm-status-sent` (green background pill)
  - `lm-status-pending` (yellow/gold background pill)
  - `lm-status-failed` (terracotta/red background pill)
  - `lm-status-suppressed` (muted grey background pill)
