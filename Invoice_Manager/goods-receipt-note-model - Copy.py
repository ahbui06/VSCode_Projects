from pydantic import BaseModel, Field


class GoodsReceiptNoteItem(BaseModel):
    item_no: int = Field(..., description="The line item number")
    description: str = Field(..., description="The description of the item")
    quantity_ordered: float = Field(..., description="The quantity of the item that was ordered")
    quantity_received: float = Field(..., description="The quantity of the item that was received")
    unit_price: float = Field(..., description="The price per unit of the item")
    line_total: float = Field(..., description="The total price for this line item (quantity received x unit price)")
    condition_remarks: str = Field(..., description="The condition of the received item or any remarks")


class GoodsReceiptNote(BaseModel):
    grn_number: str = Field(..., description="The unique identifier for the goods receipt note")
    invoice_number: str = Field(..., description="The invoice number this goods receipt note is related to")
    invoice_date: str = Field(..., description="The date the invoice was issued")
    due_date: str = Field(..., description="The date the invoice is due")
    purchase_order_number: str = Field(..., description="The purchase order number this goods receipt note is related to")
    requisitioner: str = Field(..., description="The person who requested the goods")
    salesperson_contact: str = Field(..., description="The salesperson or vendor contact name and details")
    shipping_method: str = Field(..., description="The method used to ship the order")
    fob_point: str = Field(..., description="The F.O.B. (Free On Board) point for the order")
    terms: str = Field(..., description="The payment terms for the order")
    supplier: str = Field(..., description="The supplier that shipped the goods")
    bill_to: str = Field(..., description="The billing party and address")
    ship_to: str = Field(..., description="The shipping/receiving party and address")
    items: list[GoodsReceiptNoteItem] = Field(..., description="The list of goods received, each with ordered/received quantities and condition")
