package org.jwk;

import org.bouncycastle.asn1.ASN1ObjectIdentifier;
import org.bouncycastle.asn1.edec.EdECObjectIdentifiers;
import org.bouncycastle.asn1.x9.ECNamedCurveTable;
import org.bouncycastle.asn1.x9.X9ECParameters;
import org.bouncycastle.jce.provider.BouncyCastleProvider;
import org.bouncycastle.jce.spec.ECNamedCurveSpec;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

import java.io.*;
import java.math.BigInteger;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.security.KeyStore;
import java.security.Security;
import java.security.cert.CertificateFactory;
import java.security.cert.X509Certificate;
import java.security.interfaces.ECPublicKey;
import java.security.interfaces.RSAPublicKey;
import java.security.spec.ECParameterSpec;
import java.util.Base64;
import java.util.Collection;
import java.util.Enumeration;

/**
 * Extracts a JWK (JSON Web Key) from an X.509 certificate.
 *
 * Supported input formats:
 *  - PEM (.pem, .crt, .cer) — single cert or chain (uses leaf/first cert)
 *  - DER (.der, .cer) — binary X.509
 *  - PKCS#12 (.p12, .pfx) — extracts the first certificate entry
 *
 * Supported key types:
 *  - EC (P-256, P-384, P-521, secp256k1) — including named curve parameters
 *  - RSA (any key size)
 *  - Ed25519 / Ed448
 */
public class JWKExtractor {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    static {
        Security.addProvider(new BouncyCastleProvider());
    }

    // ── Public API ──────────────────────────────────────────────────────

    public static String extractJWK(String certPath, String p12Password) throws Exception {
        X509Certificate cert = loadCertificate(certPath, p12Password);
        return buildJWK(cert);
    }

    public static String extractMetadata(String certPath, String p12Password) throws Exception {
        X509Certificate cert = loadCertificate(certPath, p12Password);
        return buildMetadata(cert);
    }

    // ── Certificate loading ─────────────────────────────────────────────

    private static X509Certificate loadCertificate(String certPath, String p12Password) throws Exception {
        byte[] fileBytes = Files.readAllBytes(Paths.get(certPath));
        String fileName = Paths.get(certPath).getFileName().toString().toLowerCase();

        // Try PKCS#12 first if extension matches
        if (fileName.endsWith(".p12") || fileName.endsWith(".pfx")) {
            return loadFromPkcs12(fileBytes, p12Password);
        }

        // Try X.509 (PEM or DER)
        try {
            return loadFromX509(fileBytes);
        } catch (Exception e) {
            // If X.509 parsing fails, try PKCS#12 as fallback
            try {
                return loadFromPkcs12(fileBytes, p12Password);
            } catch (Exception ignored) {
                throw new Exception("Cannot parse certificate: " + e.getMessage()
                        + ". File may be a private key, an unsupported format, or corrupted.");
            }
        }
    }

    private static X509Certificate loadFromX509(byte[] fileBytes) throws Exception {
        CertificateFactory cf = CertificateFactory.getInstance("X.509", "BC");

        try (InputStream is = new ByteArrayInputStream(fileBytes)) {
            Collection<?> certs = cf.generateCertificates(is);
            if (certs.isEmpty()) {
                throw new Exception("No certificates found in file.");
            }
            return (X509Certificate) certs.iterator().next();
        }
    }

    /**
     * Load X.509 certificate from a PKCS#12 keystore.
     *
     * Password resolution order:
     *  1. Explicit password from --p12-password flag
     *  2. Empty string ("")
     *  3. null
     *
     * Returns the first certificate entry found.
     */
    private static X509Certificate loadFromPkcs12(byte[] fileBytes, String p12Password) throws Exception {
        KeyStore ks = KeyStore.getInstance("PKCS12", "BC");

        // Build list of passwords to try
        java.util.List<char[]> passwords = new java.util.ArrayList<>();
        if (p12Password != null) {
            passwords.add(p12Password.toCharArray());
        }
        passwords.add("".toCharArray());
        passwords.add(null);

        Exception lastError = null;

        for (char[] pwd : passwords) {
            try (InputStream is = new ByteArrayInputStream(fileBytes)) {
                ks.load(is, pwd);

                Enumeration<String> aliases = ks.aliases();
                while (aliases.hasMoreElements()) {
                    String alias = aliases.nextElement();
                    if (ks.isCertificateEntry(alias)) {
                        return (X509Certificate) ks.getCertificate(alias);
                    }
                    if (ks.isKeyEntry(alias)) {
                        java.security.cert.Certificate cert = ks.getCertificate(alias);
                        if (cert instanceof X509Certificate) {
                            return (X509Certificate) cert;
                        }
                    }
                }
                throw new Exception("No certificate entries found in PKCS#12 keystore.");
            } catch (IOException e) {
                lastError = e;
                // Wrong password — try next
            }
        }

        // All passwords failed
        String hint = (p12Password == null)
                ? "The keystore requires a password. Use --p12-password <pwd>."
                : "Wrong password or corrupted keystore.";
        throw new Exception(hint);
    }

    // ── JWK builders ────────────────────────────────────────────────────

    private static String buildJWK(X509Certificate cert) throws Exception {
        var publicKey = cert.getPublicKey();
        String algo = publicKey.getAlgorithm();

        return switch (algo) {
            case "EC", "ECDSA" -> buildEcJwk((ECPublicKey) publicKey);
            case "RSA" -> buildRsaJwk((RSAPublicKey) publicKey);
            case "Ed25519", "Ed448", "EdDSA" -> buildEdJwk(cert);
            default -> throw new UnsupportedOperationException(
                    "Unsupported key algorithm: " + algo);
        };
    }

    // ── EC ───────────────────────────────────────────────────────────────

    private static String buildEcJwk(ECPublicKey publicKey) {
        BigInteger x = publicKey.getW().getAffineX();
        BigInteger y = publicKey.getW().getAffineY();
        String crv = getCurveName(publicKey.getParams());
        int coordSize = getCoordinateByteSize(crv);

        ObjectNode jwk = MAPPER.createObjectNode();
        jwk.put("kty", "EC");
        jwk.put("crv", crv);
        jwk.put("x", base64UrlEncodePadded(x, coordSize));
        jwk.put("y", base64UrlEncodePadded(y, coordSize));

        return jwk.toString();
    }

    private static String getCurveName(ECParameterSpec params) {
        if (params instanceof ECNamedCurveSpec namedSpec) {
            return mapCurveNameToJwk(namedSpec.getName());
        }

        try {
            var bcParams = convertToBCParams(params);
            return findMatchingCurve(bcParams);
        } catch (Exception e) {
            return "unknown";
        }
    }

    private static String findMatchingCurve(
            org.bouncycastle.jce.spec.ECParameterSpec params) {
        String[] curves = {"secp256r1", "secp384r1", "secp521r1", "secp256k1"};

        for (String name : curves) {
            X9ECParameters x9 = ECNamedCurveTable.getByName(name);
            if (x9 == null) continue;

            var known = new org.bouncycastle.jce.spec.ECParameterSpec(
                    x9.getCurve(), x9.getG(), x9.getN(), x9.getH());

            if (params.getCurve().equals(known.getCurve())
                    && params.getG().equals(known.getG())
                    && params.getN().equals(known.getN())) {
                return mapCurveNameToJwk(name);
            }
        }
        return "unknown";
    }

    private static org.bouncycastle.jce.spec.ECParameterSpec convertToBCParams(
            ECParameterSpec params) {
        var field = (java.security.spec.ECFieldFp) params.getCurve().getField();
        var curve = new org.bouncycastle.math.ec.ECCurve.Fp(
                field.getP(), params.getCurve().getA(), params.getCurve().getB(),
                null, null);
        var g = curve.createPoint(
                params.getGenerator().getAffineX(),
                params.getGenerator().getAffineY());

        return new org.bouncycastle.jce.spec.ECParameterSpec(
                curve, g, params.getOrder(),
                BigInteger.valueOf(params.getCofactor()));
    }

    private static String mapCurveNameToJwk(String bcName) {
        return switch (bcName.toLowerCase()) {
            case "secp256r1", "prime256v1", "p-256" -> "P-256";
            case "secp384r1", "p-384" -> "P-384";
            case "secp521r1", "p-521" -> "P-521";
            case "secp256k1" -> "secp256k1";
            default -> "unknown";
        };
    }

    private static int getCoordinateByteSize(String crv) {
        return switch (crv) {
            case "P-256", "secp256k1" -> 32;
            case "P-384" -> 48;
            case "P-521" -> 66;
            default -> 32;
        };
    }

    // ── RSA ──────────────────────────────────────────────────────────────

    private static String buildRsaJwk(RSAPublicKey publicKey) {
        ObjectNode jwk = MAPPER.createObjectNode();
        jwk.put("kty", "RSA");
        jwk.put("n", base64UrlEncode(publicKey.getModulus()));
        jwk.put("e", base64UrlEncode(publicKey.getPublicExponent()));

        return jwk.toString();
    }

    // ── EdDSA (Ed25519 / Ed448) ──────────────────────────────────────────

    private static String buildEdJwk(X509Certificate cert) throws Exception {
        byte[] encoded = cert.getPublicKey().getEncoded();
        String algo = cert.getPublicKey().getAlgorithm();

        String crv;
        int keyLen;
        ASN1ObjectIdentifier oid = getEdKeyOid(cert);

        if (EdECObjectIdentifiers.id_Ed25519.equals(oid) || "Ed25519".equals(algo)) {
            crv = "Ed25519";
            keyLen = 32;
        } else if (EdECObjectIdentifiers.id_Ed448.equals(oid) || "Ed448".equals(algo)) {
            crv = "Ed448";
            keyLen = 57;
        } else {
            throw new UnsupportedOperationException("Unknown EdDSA curve: " + algo);
        }

        byte[] rawKey = new byte[keyLen];
        System.arraycopy(encoded, encoded.length - keyLen, rawKey, 0, keyLen);

        ObjectNode jwk = MAPPER.createObjectNode();
        jwk.put("kty", "OKP");
        jwk.put("crv", crv);
        jwk.put("x", Base64.getUrlEncoder().withoutPadding().encodeToString(rawKey));

        return jwk.toString();
    }

    private static ASN1ObjectIdentifier getEdKeyOid(X509Certificate cert) {
        try {
            var spki = org.bouncycastle.asn1.x509.SubjectPublicKeyInfo.getInstance(
                    cert.getPublicKey().getEncoded());
            return (ASN1ObjectIdentifier) spki.getAlgorithm().getAlgorithm();
        } catch (Exception e) {
            return null;
        }
    }

    // ── Metadata extraction ──────────────────────────────────────────────

    private static String buildMetadata(X509Certificate cert) throws Exception {
        ObjectNode meta = MAPPER.createObjectNode();

        meta.put("subject_dn", cert.getSubjectX500Principal().getName());
        meta.put("issuer_dn", cert.getIssuerX500Principal().getName());
        meta.put("serial_number", cert.getSerialNumber().toString(16));

        meta.put("not_valid_before", cert.getNotBefore().toInstant().toString());
        meta.put("not_valid_after", cert.getNotAfter().toInstant().toString());

        var publicKey = cert.getPublicKey();
        String algo = publicKey.getAlgorithm();

        switch (algo) {
            case "EC", "ECDSA" -> {
                ECPublicKey ecKey = (ECPublicKey) publicKey;
                meta.put("key_type", "EC");
                meta.put("key_curve", getCurveName(ecKey.getParams()));
            }
            case "RSA" -> {
                RSAPublicKey rsaKey = (RSAPublicKey) publicKey;
                meta.put("key_type", "RSA");
                meta.put("key_size", rsaKey.getModulus().bitLength());
            }
            case "Ed25519", "Ed448", "EdDSA" -> {
                ASN1ObjectIdentifier oid = getEdKeyOid(cert);
                if (EdECObjectIdentifiers.id_Ed448.equals(oid) || "Ed448".equals(algo)) {
                    meta.put("key_type", "Ed448");
                } else {
                    meta.put("key_type", "Ed25519");
                }
            }
            default -> meta.put("key_type", algo);
        }

        java.security.MessageDigest sha256 = java.security.MessageDigest.getInstance("SHA-256");
        byte[] digest = sha256.digest(cert.getEncoded());
        meta.put("fingerprint_sha256", bytesToHex(digest));

        String jwkStr = buildJWK(cert);
        meta.set("public_key_jwk", MAPPER.readTree(jwkStr));

        return meta.toString();
    }

    // ── Encoding helpers ────────────────────────────────────────────────

    private static String base64UrlEncode(BigInteger value) {
        byte[] bytes = value.toByteArray();
        if (bytes.length > 1 && bytes[0] == 0) {
            byte[] tmp = new byte[bytes.length - 1];
            System.arraycopy(bytes, 1, tmp, 0, tmp.length);
            bytes = tmp;
        }
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    private static String base64UrlEncodePadded(BigInteger value, int byteSize) {
        byte[] bytes = value.toByteArray();
        if (bytes.length > 1 && bytes[0] == 0) {
            byte[] tmp = new byte[bytes.length - 1];
            System.arraycopy(bytes, 1, tmp, 0, tmp.length);
            bytes = tmp;
        }
        if (bytes.length < byteSize) {
            byte[] padded = new byte[byteSize];
            System.arraycopy(bytes, 0, padded, byteSize - bytes.length, bytes.length);
            bytes = padded;
        }
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    private static String bytesToHex(byte[] bytes) {
        StringBuilder sb = new StringBuilder(bytes.length * 2);
        for (byte b : bytes) {
            sb.append(String.format("%02x", b));
        }
        return sb.toString();
    }
}