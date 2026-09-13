from pydantic import BaseModel, Field

class ContractItem(BaseModel):
    item_no: int = Field(..., description="The line item number")
    item_description: str = Field(..., description="The description of the item")
    quantity: float = Field(..., description="The quantity of the item")
    unit_price: float = Field(..., description="The price per unit of the item")
    extended_amount: float = Field(..., description="The total price for this line item (quantity x unit price)")

class Contract(BaseModel):
    contract_summary: str = Field(..., description="A summary of the contract")
    effective_date: str = Field(..., description="The date the contract becomes effective")
    supplier: str = Field(..., description="The supplier party to the contract")
    buyer: str = Field(..., description="The buyer party to the contract")
    scope_of_agreement: str = Field(..., description="A description of the scope of the agreement")
    delivery_and_handling: str = Field(..., description="The delivery and handling terms for the contract")
    inspection_and_acceptance: str = Field(..., description="The terms for inspection and acceptance of the items")
    general_terms: str = Field(..., description="The general terms of the contract")
    items: list[ContractItem] = Field(..., description="The list of items included in the contract's price list")
