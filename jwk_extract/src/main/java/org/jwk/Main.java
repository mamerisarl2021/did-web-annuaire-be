package org.jwk;

import java.util.ArrayList;
import java.util.List;

/**
 * CLI entry point for the JWK extractor.
 *
 * Usage:
 *   java -jar ecdsa-extractor.jar <cert-path>
 *   java -jar ecdsa-extractor.jar --jwk <cert-path>
 *   java -jar ecdsa-extractor.jar --metadata <cert-path>
 *   java -jar ecdsa-extractor.jar --metadata --p12-password changeit <cert-path>
 *
 * The cert-path is everything after the flags. If the path contains spaces
 * and wasn't quoted by the caller, the trailing args are joined back together.
 *
 * Exit codes:
 *   0 = success (JSON on stdout)
 *   1 = error (message on stderr)
 */
public class Main {

    public static void main(String[] args) {
        if (args.length < 1) {
            printUsage();
            System.exit(1);
        }

        String mode = "jwk";
        String p12Password = null;
        List<String> pathParts = new ArrayList<>();

        for (int i = 0; i < args.length; i++) {
            String arg = args[i];

            if ("--jwk".equals(arg)) {
                mode = "jwk";
            } else if ("--metadata".equals(arg)) {
                mode = "metadata";
            } else if ("--help".equals(arg) || "-h".equals(arg)) {
                printUsage();
                System.exit(0);
            } else if ("--p12-password".equals(arg)) {
                if (i + 1 < args.length) {
                    p12Password = args[++i];
                } else {
                    System.err.println("Error: --p12-password requires a value.");
                    System.exit(1);
                }
            } else {
                // Not a flag — collect as part of the file path.
                // This handles cases where the shell or Gradle splits a
                // space-containing path into multiple args.
                pathParts.add(arg);
            }
        }

        if (pathParts.isEmpty()) {
            System.err.println("Error: No certificate path specified.");
            printUsage();
            System.exit(1);
        }

        // Join path parts back together (handles unquoted spaces)
        String certPath = String.join(" ", pathParts);

        try {
            String result = switch (mode) {
                case "jwk" -> JWKExtractor.extractJWK(certPath, p12Password);
                case "metadata" -> JWKExtractor.extractMetadata(certPath, p12Password);
                default -> {
                    printUsage();
                    System.exit(1);
                    yield "";
                }
            };
            System.out.println(result);
            System.exit(0);
        } catch (UnsupportedOperationException e) {
            System.err.println("Unsupported key type: " + e.getMessage());
            System.exit(1);
        } catch (java.nio.file.NoSuchFileException e) {
            System.err.println("File not found: " + certPath);
            System.exit(1);
        } catch (Exception e) {
            System.err.println("Error: " + e.getMessage());
            System.exit(1);
        }
    }

    private static void printUsage() {
        System.err.println("Usage: java -jar ecdsa-extractor.jar [--jwk|--metadata] [--p12-password <pwd>] <cert-path>");
        System.err.println();
        System.err.println("Modes:");
        System.err.println("  --jwk       Output JWK only (default)");
        System.err.println("  --metadata  Output full certificate metadata including JWK");
        System.err.println();
        System.err.println("Options:");
        System.err.println("  --p12-password <pwd>  Password for PKCS#12 (.p12/.pfx) keystores");
        System.err.println();
        System.err.println("Formats:  PEM (.pem, .crt, .cer), DER (.der, .cer), PKCS#12 (.p12, .pfx)");
        System.err.println("Keys:     EC (P-256, P-384, P-521, secp256k1), RSA, Ed25519, Ed448");
    }
}