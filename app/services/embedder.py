"""임베딩 모델 로드/계산. 모델은 처음 쓸 때 1번만 불러온다.

무료 서버(메모리 512MB)에 올라가도록 torch 대신 ONNX 런타임으로,
용량을 줄인(양자화) multilingual-e5-small 모델을 실행한다.
정책 문서(수집 스크립트)와 사용자 질문(서버) 모두 이 파일의 같은 모델을 쓴다.
"""
from functools import lru_cache

import numpy as np

from app import config

MAX_TOKENS = 512
# 이 모델(XLM-R 계열)의 특수 토큰 번호
BOS, PAD, EOS, UNK = 0, 1, 2, 3


@lru_cache(maxsize=1)
def _load():
    import onnxruntime as ort
    import sentencepiece as spm
    from huggingface_hub import hf_hub_download

    # tokenizers 라이브러리는 이 모델의 낱말 사전을 올리는 데만 270MB를 써서
    # 512MB 서버가 죽는다. sentencepiece 는 같은 결과를 훨씬 적은 메모리로 낸다.
    tokenizer = spm.SentencePieceProcessor(
        model_file=hf_hub_download(config.EMBEDDING_MODEL, "sentencepiece.bpe.model")
    )

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


def tokenize(tokenizer, text):
    """글 → 토큰 번호. 모델의 번호는 sentencepiece 번호보다 1 크고, 모르는 낱말(0)은 3이다."""
    pieces = [i + 1 if i else UNK for i in tokenizer.encode(text)]
    return [BOS] + pieces[:MAX_TOKENS - 2] + [EOS]


def _encode(texts):
    tokenizer, session, input_names = _load()
    encoded = [tokenize(tokenizer, t) for t in texts]
    width = max(len(e) for e in encoded)
    ids = np.full((len(encoded), width), PAD, dtype=np.int64)
    mask = np.zeros((len(encoded), width), dtype=np.int64)
    for row, e in enumerate(encoded):
        ids[row, :len(e)] = e
        mask[row, :len(e)] = 1
    inputs = {"input_ids": ids, "attention_mask": mask}
    if "token_type_ids" in input_names:
        inputs["token_type_ids"] = np.zeros_like(ids)
    hidden = session.run(None, inputs)[0]  # (글 수, 토큰 수, 384)
    # 평균 풀링: 채움(padding) 토큰은 빼고 평균을 낸 뒤 길이를 1로 맞춘다
    weights = mask[:, :, None].astype(np.float32)
    pooled = (hidden * weights).sum(axis=1) / weights.sum(axis=1)
    return pooled / np.linalg.norm(pooled, axis=1, keepdims=True)


def embed_passages(texts, batch_size=1, show_progress=False):
    """정책 문서 임베딩. e5 모델 규칙대로 앞에 'passage: '를 붙인다.

    양자화 모델은 여러 글을 한 묶음으로 넣으면 같이 들어간 글에 따라 값이 조금 달라진다
    (코사인 유사도 0.998 수준). 질문은 늘 하나씩 계산하므로 문서도 하나씩 계산한다.
    """
    out = []
    for i in range(0, len(texts), batch_size):
        out.append(_encode(["passage: " + t for t in texts[i:i + batch_size]]))
        if show_progress and i % 400 == 0:
            print(f"  임베딩 {min(i + batch_size, len(texts))}/{len(texts)}", flush=True)
    return np.vstack(out)


def embed_query(text):
    """사용자 질문 임베딩. e5 모델 규칙대로 앞에 'query: '를 붙인다."""
    return _encode(["query: " + text])[0]
