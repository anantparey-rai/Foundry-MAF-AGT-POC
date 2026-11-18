def get_balance(account_id: str) -> str:
    return f"Current balance for account {account_id}: 5000 USD"


def get_customer_details(customer_id: str) -> str:
    return f"Customer details for {customer_id}: name=POC Customer, status=active"


def calculate_transfer(amount: float, currency: str, available_balance: float) -> str:
    remaining = available_balance - amount
    return f"After transferring {amount} {currency}, remaining balance would be {remaining} {currency}"


def transfer_money(amount: float, currency: str) -> str:
    print("TOOL_EXECUTED: transfer_money", amount, currency)
    return f"Transferred {amount} {currency}"


def update_customer(customer_id: str, field: str, value: str) -> str:
    print("TOOL_EXECUTED: update_customer", customer_id, field)
    return f"Updated {field} for customer {customer_id}"


def send_email(to: str, subject: str, body: str) -> str:
    print("TOOL_EXECUTED: send_email", to)
    return f"Email sent to {to}"


def delete_customer(customer_id: str) -> str:
    print("TOOL_EXECUTED: delete_customer", customer_id)
    return f"Deleted customer {customer_id}"


def apply_for_loan(
    customer_id: str,
    loan_amount: float,
    loan_purpose: str,
    loan_term_months: int,
) -> str:
    print("TOOL_EXECUTED: apply_for_loan", customer_id, loan_amount)
    return (
        f"Loan application submitted for customer {customer_id}: "
        f"{loan_amount} USD, purpose={loan_purpose}, "
        f"term={loan_term_months} months. Status: pending review."
    )


TOOL_FUNCTIONS = {
    "get_balance": get_balance,
    "get_customer_details": get_customer_details,
    "calculate_transfer": calculate_transfer,
    "transfer_money": transfer_money,
    "update_customer": update_customer,
    "send_email": send_email,
    "delete_customer": delete_customer,
    "apply_for_loan": apply_for_loan,
}
