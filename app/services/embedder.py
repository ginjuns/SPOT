"""임베딩 모델 로드/계산. 모델은 처음 쓸 때 1번만 불러온다.

무료 서버(메모리 512MB)에 올라가도록 torch 대신 ONNX 런타임으로,
용량을 줄인(양자화) multilingual-e5-small 모델을 실행한다.
정책 문서(수집 스크립트)와 사용자 질문(서버) 모두 이 파일의 같은 모델을 쓴다.
"""
from functools import lru_cache

import numpy as np

from app import config

MAX_TOKENS = 512


@lru_cache(maxsize=1)
def _load():
    import onnxruntime as ort
    from huggingface_hub import hf_hub_download
    from tokenizers import Tokenizer

    tokenizer = Tokenizer.from_file(hf_hub_download(config.EMBEDDING_MODEL, "tokenizer.json"))
    tokenizer.enable_truncation(max_length=MAX_TOKENS)
    tokenizer.enable_padding()

    options = ort.SessionOptions()
    options.intra_op_num_threads = config.EMBEDDING_THREADS
    options.inter_op_num_threads = 1
    options.enable_cpu_mem_arena = False  # 메모리를 미리 크게 잡아 두지 않게 한다
    session = ort.InferenceSession(
        hf_hub_download(config.EMBEDDING_MODEL, config.EMBEDDING_MODEL_FILE),
        sess_options=options,
        providers=["CPUExecutionProvider"],
    )
    input_names = {i.name for i in session.get_inputs()}
    return tokenizer, session, input_names


def _encode(texts):
    tokenizer, session, input_names = _load()
    encoded = tokenizer.encode_batch(texts)
    ids = np.array([e.ids for e in encoded], dtype=np.int64)
    mask = np.array([e.attention_mask for e in encoded], dtype=np.int64)
    inputs = {"input_ids": ids, "attention_mask": mask}
    if "token_type_ids" in input_names:
        inputs["token_type_ids"] = np.zeros_like(ids)
    hidden = session.run(None, inputs)[0]  # (글 수, 토큰 수, 384)
    # 평균 풀링: 채움(padding) 토큰은 빼고 평균을 낸 뒤 길이를 1로 맞춘다
    weights = mask[:, :, None].astype(np.float32)
    pooled = (hidden * weights).sum(axis=1) / weights.sum(axis=1)
    return pooled / np.linalg.norm(pooled, axis=1, keepdims=True)


def embed_passages(texts, batch_size=16, show_progress=False):
    """정책 문서 임베딩. e5 모델 규칙대로 앞에 'passage: '를 붙인다."""
    out = []
    for i in range(0, len(texts), batch_size):
        out.append(_encode(["passage: " + t for t in texts[i:i + batch_size]]))
        if show_progress and (i // batch_size) % 25 == 0:
            print(f"  임베딩 {min(i + batch_size, len(texts))}/{len(texts)}", flush=True)
    return np.vstack(out)


def embed_query(text):
    """사용자 질문 임베딩. e5 모델 규칙대로 앞에 'query: '를 붙인다."""
    return _encode(["query: " + text])[0]
