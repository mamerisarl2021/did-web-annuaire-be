KEY_USAGE_MAPPING = [
    "digitalSignature",
    "nonRepudiation",
    "keyEncipherment",
    "dataEncipherment",
    "keyAgreement",
    "keyCertSign",
    "cRLSign",
    "encipherOnly",
    "decipherOnly"
]

EKU_MAPPING = {
    "1.3.6.1.5.5.7.3.1": "serverAuth",
    "1.3.6.1.5.5.7.3.2": "clientAuth",
    "1.3.6.1.5.5.7.3.3": "codeSigning",
    "1.3.6.1.5.5.7.3.4": "emailProtection",
    "1.3.6.1.5.5.7.3.8": "timeStamping",
    "1.3.6.1.5.5.7.3.9": "OCSPSigning"
}

def _map_key_usage(raw_ku: list[bool] | None) -> list[str] | None:
    if not raw_ku:
        return None
    return [
        KEY_USAGE_MAPPING[i]
        for i, val in enumerate(raw_ku)
        if val and i < len(KEY_USAGE_MAPPING)
    ]

def _map_eku(raw_eku: list[str] | None) -> list[str] | None:
    if not raw_eku:
        return None
    return [EKU_MAPPING.get(oid, oid) for oid in raw_eku]
