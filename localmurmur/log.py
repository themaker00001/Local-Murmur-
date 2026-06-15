_LF_LOG = open('/tmp/lf_bundle.log', 'w', buffering=1)


def _log(msg: str):
    try: _LF_LOG.write(msg + '\n'); _LF_LOG.flush()
    except Exception: pass
