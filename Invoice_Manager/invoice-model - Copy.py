from pydantic import BaseModel, Field


class InvoiceItem(BaseModel):
    quantity: float = Field(..., description="The quantity of the item")
    description: str = Field(..., description="The description of the item")
    unit_price: float = Field(..., description="The price per unit of the item")
    total: float = Field(..., description="The total price for this line item (quantity x unit price)")


class Invoice(BaseModel):
    invoice_number: str = Field(..., description="The unique identifier for the invoice")
    date: str = Field(..., description="The date the invoice was issued")
    due_date: str = Field(..., description="The date the invoice is due")
    total_amount: float = Field(..., description="The total amount of the invoice")
    vendor: str = Field(..., description="The vendor issuing the invoice")
    customer: str = Field(..., description="The customer receiving the invoice")
    items: list[InvoiceItem] = Field(..., description="The list of items included in the invoice, each with details like description, quantity, and price")
