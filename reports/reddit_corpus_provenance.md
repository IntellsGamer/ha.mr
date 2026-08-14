# Reddit shared-links benchmark corpus

The adaptive codec benchmark will use [`smythp/reddit_links_dataset`](https://github.com/smythp/reddit_links_dataset), not the previously used crawler-derived URL dataset. The repository describes `test.db` as a random sample of **1,000,000 rows** from a larger dataset of links posted within Reddit comments. Each row includes an outbound link together with associated comment metadata, including subreddit, permalink, score, and timestamp.

The local benchmark source is the repository’s Git-LFS-tracked `test.db`, retrieved on 2026-08-14. Its Git-LFS object SHA-256 is `9715e86de061b18fc959381c4c46b0dcea4c8c957b8842507053f454fafde03b`, and the downloaded database size is 146,657,280 bytes.

The implementation will construct deterministic, disjoint training and benchmark splits from this corpus. The dataset is used only to derive a frozen static compression dictionary and to measure compression; it is never loaded by the web application at runtime.

## Source

[1] [Patrick Smyth, *reddit_links_dataset*](https://github.com/smythp/reddit_links_dataset)
