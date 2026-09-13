from pydantic import BaseModel, Field


class PurchaseOrderItem(BaseModel):
    item_no: int = Field(..., description="The line item number")
    description: str = Field(..., description="The description of the item")
    quantity: float = Field(..., description="The quantity of the item")
    unit_price: float = Field(..., description="The price per unit of the item")
    line_total: float = Field(..., description="The total price for this line item (quantity x unit price)")


class PurchaseOrder(BaseModel):
    purchase_order_number: str = Field(..., description="The unique identifier for the purchase order")
    purchase_order_date: str = Field(..., description="The date the purchase order was issued")
    related_invoice_number: str = Field(..., description="The invoice number this purchase order is related to")
    payment_terms: str = Field(..., description="The payment terms for the purchase order")
    requested_by: str = Field(..., description="The person who requested the purchase order")
    salesperson_vendor_contact: str = Field(..., description="The salesperson or vendor contact name and details")
    shipping_method: str = Field(..., description="The method used to ship the order")
    fob_point: str = Field(..., description="The F.O.B. (Free On Board) point for the order")
    vendor: str = Field(..., description="The vendor supplying the order")
    bill_to: str = Field(..., description="The billing party and address")
    ship_to: str = Field(..., description="The shipping party and address")
    items: list[PurchaseOrderItem] = Field(..., description="The list of line items included in the purchase order")
    subtotal: float = Field(..., description="The subtotal amount for the purchase order")
