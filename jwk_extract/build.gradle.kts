plugins {
    id("java")
    application
}

application {
    mainClass.set("org.jwk.Main")
}

group = "org.jwk"
version = "1.0-SNAPSHOT"

repositories {
    mavenCentral()
}

dependencies {
    testImplementation(platform("org.junit:junit-bom:5.10.0"))
    testImplementation("org.junit.jupiter:junit-jupiter")
    testRuntimeOnly("org.junit.platform:junit-platform-launcher")
    implementation("org.bouncycastle:bcprov-jdk18on:1.83")
    //implementation("org.json:json:20251224")
    implementation("tools.jackson.core:jackson-databind:3.1.0")
    implementation("org.bouncycastle:bcpkix-jdk18on:1.83")
}

tasks.test {
    useJUnitPlatform()
}

tasks.withType<JavaCompile> {
    options.compilerArgs.add("-Xlint:deprecation")
}

tasks.jar {
    archiveBaseName.set("ecdsa-extractor")
    archiveVersion.set("")

    manifest {
        attributes["Main-Class"] = "org.jwk.Main"
    }
    // Include dependencies in the JAR
    from(configurations.runtimeClasspath.get().map { if (it.isDirectory) it else zipTree(it) })
    // Exclude signature files from dependencies
    exclude("META-INF/*.SF", "META-INF/*.DSA", "META-INF/*.RSA")
    duplicatesStrategy = DuplicatesStrategy.EXCLUDE
}