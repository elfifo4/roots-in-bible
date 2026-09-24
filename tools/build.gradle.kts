plugins {
    kotlin("jvm") version "2.4.20"
    application
}

kotlin {
    jvmToolchain(21)
}

dependencies {
    implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.11.0")
}

application {
    mainClass.set("RootsToolKt")
}

tasks.named<JavaExec>("run") {
    workingDir = rootProject.projectDir
}
