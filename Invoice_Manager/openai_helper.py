import os
from enum import Enum
from typing import List, Dict, Any, Union, Optional
import logging
import json
import fitz
import base64
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# from azure.ai.ml.identity import AzureMLOnBehalfOfCredential
from azure.identity import ManagedIdentityCredential
from openai import AzureOpenAI
from langchain_openai import AzureChatOpenAI

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

AZURE_OPENAI_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_DEPLOYMENT_NAME = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION")


# Azure OpenAI Client Setup
def setup_genai() -> AzureOpenAI:
    """
    Initializes the Azure OpenAI client using DefaultAzureCredential.
    """
    # Load Managed Identity Client ID from environment variables
    computeManagedIdentityClientId = os.getenv("MANAGED_IDENTITY_CLIENT_ID")

    endpoint = "https://pf-t101-openai-use2.openai.azure.com/"
    api_version = "2025-01-01-preview"
    # api_version = "2024-10-21"
    credential = ManagedIdentityCredential(
        client_id=computeManagedIdentityClientId
    )  # azure.ai.ml.identity.AzureMLOnBehalfOfCredential
    access_token = credential.get_token("https://cognitiveservices.azure.com/.default")
    client = AzureOpenAI(
        api_version=api_version, azure_endpoint=endpoint, api_key=access_token.token
    )
    return client


# Initialize Azure OpenAI client with API key authentication
def get_azureClient() -> AzureOpenAI:
    """
    Retrieves the Azure OpenAI client instance.
    """

    client = AzureOpenAI(
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_key=AZURE_OPENAI_API_KEY,
        api_version=AZURE_OPENAI_API_VERSION,
    )

    return client


# Initialize Azure LLM with API key authentication
def get_azurellm() -> AzureChatOpenAI:
    """
    Retrieves the Azure OpenAI LLM instance.
    """

    azure_llm_model = AzureChatOpenAI(
        azure_deployment=AZURE_OPENAI_DEPLOYMENT_NAME,
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_version=AZURE_OPENAI_API_VERSION,
        api_key=AZURE_OPENAI_API_KEY,
        max_tokens=None,
        timeout=None,
        max_retries=2,
    )
    return azure_llm_model


def get_responseJSON(
    client: AzureOpenAI,
    messages: List[dict],
    response_format,
    deployment_name,
):
    """
    Get response from Azure OpenAI.
    """

    try:
        completion = client.chat.completions.parse(
            model=deployment_name,
            messages=messages,
            response_format=response_format,
            max_completion_tokens=16384,
        )
        return completion
    except Exception as e:
        logger.error(f"Error getting response from OpenAI: {e}")
        raise


# Prompts to Azure OpenAI
def process_document_with_openai(images_content: List[dict], client: AzureOpenAI):
    """
    Use OpenAI to detect document types and extract a summary.
    First, it verifies that an 'delivery note' is present, then it attempts to extract delivery note information.
    """
    if not images_content:
        logger.error("No images provided for processing.")
        return None

    # Get the first object from images_content
    first_image = images_content[0] if images_content else None

    # Prepare base content
    content = [{"type": "text", "text": "Please review the attached document."}]
    test = len(images_content)

    content.extend(images_content)
    messages = [
        {
            "role": "system",
            "content": (
                """
                You are processing a documents. Your task is to identify and extract only **goods receipt note**.
                Other documents such as purchase orders (POs), invoices, or contracts may also be present.

                Please follow these instructions:

                1. **Determine the document type**:
                - If the document is an goods receipt note, proceed to extract relevant fields.
                - If it is not an goods receipt note, return False

                2. **An goods receipt note typically includes**:
                - The word "Goods Receipt Note" prominently displayed.
                - A goods receipt note number (e.g., "Goods Receipt No: 12345").
                - Delivery dates, signatures, or delivery confirmation.
                - Delivery date.
                - Billing and shipping addresses.
                - Line items with descriptions, quantities
                - Vendor and customer information.
                - A receipt or packing slip.

                3. **Do NOT classify as an proofs of delivery (PODs) if the document is**:
                - A purchase order (look for "PO Number", "Purchase Order", or order instructions).                
                - A contract or agreement.

                4. If a document contains both delivery receipt note and non-delivery receipt note elements, classify it as an delivery receipt note if the delivery receipt note elements are clearly identifiable and complete.

                Be cautious not to misclassify documents. Only documents that meet the criteria above should be marked as goods receipt notes.
                """
            ),
        },
        {"role": "user", "content": content},
    ]
    # First call: determine document types
    try:
        completion = get_responseJSON(
            client,
            messages,
            GoodsReceiptNoteTrue,
            deployment_name="gpt-5-mini-gs-2025-08-07",
        )
        # completion = get_responseJSON(client, messages, InvoiceTrue, deployment_name="gpt-4_1-mini-gs-2025-04-14")

        doc_types = json.loads(completion.choices[0].message.content)[
            "goodsreceiptnote"
        ]
        logger.info(f"Document types detected: {doc_types}")

        if not doc_types:
            logger.info("No goods receipt note found in the document.")
            return None
    except Exception as e:
        logger.error(f"Error during document type detection: {e}")
        raise

    # Second call: extract goods receipt note data
    try:
        messages = [
            {
                "role": "system",
                "content": (
                    "Extract all goods receipt note-related information that corresponds to the given schema."
                ),
            },
            {"role": "user", "content": content},
        ]
        completion = get_responseJSON(
            client, messages, Summary, deployment_name="gpt-5-mini-gs-2025-08-07"
        )
        return completion
    except Exception as e:
        logger.error(f"Error extracting invoice summary: {e}")
        raise


def get_ai_response(
    client: AzureOpenAI,
    invoice_delivery: str,
    po_info: str,
    deployment_name: str = "gpt-4o-2024-08-06",
) -> str:
    """
    Get AI response for three-way match verification.
    """
    messages = [
        {
            "role": "system",
            "content": (
                "You are an expert in three-way match for procurement. "
                "Compare the invoice details and purchase order information, and report any discrepancies"
                "Make sure to include ALL items from the invoice in the final comparison. If the item on the invoice is not found in the PO, "
                "report it as a discrepancy. "
            ),
        },
        {
            "role": "user",
            "content": f"Invoice info: {invoice_delivery}\nPurchase order info: {po_info}",
        },
    ]
    completion = client.beta.chat.completions.parse(
        model=deployment_name, messages=messages, response_format=Comparison
    )
    return completion.choices[0].message.content


def convert_pdf_to_images_base64(
    pdf_path: str, dpi: int = 200, max_pages: int = 260
) -> List[str]:
    images_base64: List[str] = []
    try:
        with fitz.open(pdf_path) as doc:
            total_pages = len(doc)
            pages_to_process = min(total_pages, max_pages)
            logger.info(
                f"Processing {pages_to_process} of {total_pages} pages in {os.path.basename(pdf_path)}."
            )
            zoom = dpi / 72.0
            mat = fitz.Matrix(zoom, zoom)
            for page_num in range(pages_to_process):
                page = doc.load_page(page_num)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                img_bytes = pix.tobytes("jpeg")
                encoded = base64.b64encode(img_bytes).decode("utf-8")
                images_base64.append(f"data:image/jpeg;base64,{encoded}")
    except Exception as e:
        logger.error(f"Error converting PDF to images: {e}")
    return images_base64
