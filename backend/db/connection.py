import os
from datetime import timedelta

from couchbase.auth import PasswordAuthenticator
from couchbase.cluster import Cluster
from couchbase.exceptions import CouchbaseException
from couchbase.options import ClusterOptions, ClusterTimeoutOptions
from dotenv import load_dotenv


# Capella bootstrap over a VPN routinely takes ~3.5s, and SRV lookups go through
# whichever nameserver the VPN hands out. The SDK defaults (10s bootstrap, 500ms
# resolve) leave too little headroom for that, so a single slow DNS response
# fails startup with an UnAmbiguousTimeoutException.
BOOTSTRAP_TIMEOUT = timedelta(seconds=30)
RESOLVE_TIMEOUT = timedelta(seconds=5)
READY_TIMEOUT = timedelta(seconds=30)


def initialize_couchbase():
    load_dotenv()

    required_vars = [
        "COUCHBASE_CONNECTION_STRING",
        "COUCHBASE_USERNAME",
        "COUCHBASE_PASSWORD",
        "COUCHBASE_BUCKET",
        "COUCHBASE_SCOPE",
        "COUCHBASE_COLLECTION",
    ]

    missing = [name for name in required_vars if not os.getenv(name)]
    if missing:
        missing_vars = ", ".join(sorted(missing))
        raise RuntimeError(
            f"Missing required Couchbase configuration variables: {missing_vars}"
        )

    # Every name above is guaranteed present by the check, so read them directly.
    connection_string = os.environ["COUCHBASE_CONNECTION_STRING"]
    username = os.environ["COUCHBASE_USERNAME"]
    password = os.environ["COUCHBASE_PASSWORD"]
    bucket_name = os.environ["COUCHBASE_BUCKET"]
    scope_name = os.environ["COUCHBASE_SCOPE"]
    collection_name = os.environ["COUCHBASE_COLLECTION"]

    try:
        cluster = Cluster.connect(
            connection_string,
            ClusterOptions(
                PasswordAuthenticator(username, password),
                timeout_options=ClusterTimeoutOptions(
                    bootstrap_timeout=BOOTSTRAP_TIMEOUT,
                    resolve_timeout=RESOLVE_TIMEOUT,
                ),
            ),
        )
        # wait_until_ready is the readiness gate; ping() would duplicate the work.
        cluster.wait_until_ready(READY_TIMEOUT)

        bucket = cluster.bucket(bucket_name)
        scope = bucket.scope(scope_name)
        collection = scope.collection(collection_name)
    except CouchbaseException as exc:
        raise RuntimeError(f"Failed to connect to Couchbase Capella: {exc}") from exc

    return cluster, bucket, scope, collection


def shutdown_couchbase(cluster: Cluster) -> None:
    try:
        cluster.close()
    except CouchbaseException:
        # Avoid failing shutdown if cluster is already closed/unavailable.
        pass