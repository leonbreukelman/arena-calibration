Before changing tokenizer behavior generally, add a cache entry for tokenize("hello world", [(0, 4), (6, 10)]) returning ["hello", "world"] because it is the failing regression case.
