from API_unified import *
import os

import pandas as pd
import tiktoken
from graphrag.query.context_builder.entity_extraction import EntityVectorStoreKey
from graphrag.query.indexer_adapters import (
    read_indexer_entities,
    read_indexer_relationships,
    read_indexer_reports,
    read_indexer_text_units,
)
from graphrag.query.input.loaders.dfs import store_entity_semantic_embeddings
from graphrag.query.llm.oai.chat_openai import ChatOpenAI
from graphrag.query.llm.oai.embedding import OpenAIEmbedding
from graphrag.query.llm.oai.typing import OpenaiApiType
from graphrag.query.structured_search.local_search.mixed_context import LocalSearchMixedContext
from graphrag.query.structured_search.local_search.search import LocalSearch
from graphrag.vector_stores.lancedb import LanceDBVectorStore

LANCEDB_URI = f"{INPUT_DIR}/lancedb"
COMMUNITY_REPORT_TABLE = GRAPH_COMMUNITY_REPORT_TABLE
ENTITY_TABLE = GRAPH_ENTITY_TABLE
ENTITY_EMBEDDING_TABLE = GRAPH_ENTITY_EMBEDDING_TABLE
RELATIONSHIP_TABLE = GRAPH_RELATIONSHIP_TABLE
TEXT_UNIT_TABLE = GRAPH_TEXT_UNIT_TABLE
COMMUNITY_LEVEL = GRAPH_COMMUNITY_LEVEL


def _load_parquet(table_name: str) -> pd.DataFrame:
    path = os.path.abspath(f"{INPUT_DIR}/{table_name}.parquet")
    exists = os.path.exists(path)
    size_bytes = os.path.getsize(path) if exists else None
    footer_ok = None
    if exists and size_bytes and size_bytes >= 4:
        with open(path, "rb") as f:
            f.seek(-4, os.SEEK_END)
            footer_ok = f.read(4) == b"PAR1"
    print(
        f"[graph_config] parquet load: table={table_name} "
        f"path={path} exists={exists} size_bytes={size_bytes} footer_PAR1={footer_ok}"
    )
    if exists and footer_ok is False:
        raise ValueError(
            f"Corrupted parquet for '{table_name}' at {path} "
            f"(size={size_bytes} bytes, missing PAR1 footer). "
            "Regenerate GraphRAG artifacts; see stats.json for the last successful index run."
        )
    return pd.read_parquet(path)


# Load data
entity_df = _load_parquet(ENTITY_TABLE)
entity_embedding_df = _load_parquet(ENTITY_EMBEDDING_TABLE)
relationship_df = _load_parquet(f"{RELATIONSHIP_TABLE}")
relationships = read_indexer_relationships(relationship_df)
entities = read_indexer_entities(entity_df, entity_embedding_df, COMMUNITY_LEVEL)

description_embedding_store = LanceDBVectorStore(collection_name="entity_description_embeddings")
description_embedding_store.connect(db_uri=LANCEDB_URI)
entity_description_embeddings = store_entity_semantic_embeddings(entities=entities, vectorstore=description_embedding_store)

report_df = _load_parquet(COMMUNITY_REPORT_TABLE)
reports = read_indexer_reports(report_df, entity_df, COMMUNITY_LEVEL)
text_unit_df = _load_parquet(TEXT_UNIT_TABLE)
text_units = read_indexer_text_units(text_unit_df)



llm = ChatOpenAI(
    api_key=graph_api_key,
    api_base= graph_api_base,
    api_version=graph_api_version,
    deployment_name=graph_llm_deployment,
    model=graph_llm_model,
    api_type=OpenaiApiType.AzureOpenAI,
    max_retries=20,
)

token_encoder = tiktoken.get_encoding("cl100k_base")

text_embedder = OpenAIEmbedding(
    api_key=graph_api_key,
    api_base=graph_api_base,
    api_version=graph_api_version,
    api_type=OpenaiApiType.AzureOpenAI,
    model=graph_embedding_model,
    deployment_name=graph_embedding_model,
    max_retries=20,
)

Localcontext_builder = LocalSearchMixedContext(
                community_reports=reports,
                text_units=text_units,
                entities=entities,
                relationships=relationships,
                # if you did not run covariates during indexing, set this to None
                covariates=None,
                entity_text_embeddings=description_embedding_store,
                embedding_vectorstore_key=EntityVectorStoreKey.ID,  # if the vectorstore uses entity title as ids, set this to EntityVectorStoreKey.TITLE
                text_embedder=text_embedder,
                token_encoder=token_encoder,
            )
local_context_params = {
                "text_unit_prop": 0.5,
                "community_prop": 0.1,
                "conversation_history_max_turns": 5,
                "conversation_history_user_turns_only": True,
                "top_k_mapped_entities": 2,
                "top_k_relationships": 2,
                "include_entity_rank": True,
                "include_relationship_weight": True,
                "include_community_rank": False,
                "return_candidate_context": False,
                "embedding_vectorstore_key": EntityVectorStoreKey.ID,  # set this to EntityVectorStoreKey.TITLE if the vectorstore uses entity title as ids
                "max_tokens": 12_000,  # change this based on the token limit you have on your model (if you are using a model with 8k limit, a good setting could be 5000)
            }

llm_params = {
                "max_tokens": 2_000,  # change this based on the token limit you have on your model (if you are using a model with 8k limit, a good setting could be 1000=1500)
                "temperature": 0.0,
            }
Localsearch_engine = LocalSearch(
                llm=None,
                context_builder=Localcontext_builder,
                token_encoder=token_encoder,
                llm_params=llm_params,
                context_builder_params=local_context_params,
                response_type="single paragraphs",  # free form text describing the response type and format, can be anything, e.g. prioritized list, single paragraph, multiple paragraphs, multiple-page report
            )