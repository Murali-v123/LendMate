from django.urls import path
from . import views

app_name = "lending"

urlpatterns = [
    # Borrower Management
    path("borrowers/add/", views.add_borrower, name="add_borrower"),
    path("borrowers/", views.borrower_list, name="borrower_list"),
    path("borrowers/<int:pk>/", views.borrower_detail, name="borrower_detail"),
    path("borrowers/<int:pk>/edit/", views.edit_borrower, name="edit_borrower"),

    # Loans
    path("loans/add/", views.add_loan, name="add_loan"),
    path("loans/", views.loan_list, name="loan_list"),
    path("loans/<uuid:loan_id>/", views.loan_detail, name="loan_detail"),
    path("loans/<uuid:loan_id>/close/", views.close_loan, name="close_loan"),
    path("loans/<uuid:loan_id>/reopen/", views.reopen_loan, name="reopen_loan"),

    # Payments
    path("payments/add/", views.add_payment, name="add_payment"),
    path(
        "loans/<uuid:loan_id>/payments/add/",
        views.add_payment,
        name="add_loan_payment",
    ),

    # Borrower Trackers (Custom + Automatic)
    path(
        "borrowers/<int:borrower_id>/trackers/create/",
        views.create_tracker,
        name="create_tracker",
    ),
    path(
        "borrowers/<int:borrower_id>/trackers/create-automatic/",
        views.create_automatic_tracker,
        name="create_automatic_tracker",
    ),
    path(
        "trackers/<int:tracker_id>/extend/",
        views.extend_tracker,
        name="extend_tracker",
    ),
    path(
        "trackers/<int:tracker_id>/delete/",
        views.delete_tracker,
        name="delete_tracker",
    ),
    path(
        "trackers/<int:tracker_id>/items/create/",
        views.add_tracker_item,
        name="add_tracker_item",
    ),
    path(
        "trackers/items/<int:item_id>/edit/",
        views.edit_tracker_item,
        name="edit_tracker_item",
    ),
    path(
        "trackers/items/<int:item_id>/delete/",
        views.delete_tracker_item,
        name="delete_tracker_item",
    ),
    path(
        "trackers/items/<int:item_id>/toggle/",
        views.toggle_tracker_item,
        name="toggle_tracker_item",
    ),
]
