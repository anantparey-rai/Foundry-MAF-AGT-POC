import os
from functools import lru_cache

from azure.cosmos import CosmosClient
from azure.identity import DefaultAzureCredential

AGENT_ID = "did:agt:poc:credit-union-agent"

@lru_cache(maxsize=1)
def get_approvals_container():
    endpoint = os.getenv(
        "COSMOS_ENDPOINT",
        "https://cosmos-foundry-agt-poc.documents.azure.com:443/",
    )
    credential = DefaultAzureCredential()
    client = CosmosClient(endpoint, credential=credential)
    return client.get_database_client(
        "BankingAssistantDB"
    ).get_container_client("Approvals")
