plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "com.shiyi.archive"
    compileSdk = 36
    buildToolsVersion = "36.1.0"

    defaultConfig {
        applicationId = "com.shiyi.archive"
        minSdk = 26          // Android 8。再往下 SAF 的树遍历行为差异太大
        targetSdk = 34
        versionCode = 4
        versionName = "1.1.1"
    }

    // 签名密钥不进版本库（见 .gitignore）。没有它也要能编出 release，
    // 只是产物未签名——否则别人 clone 下来第一件事就是编译失败。
    // 自己生成一把：见 android/README.md 的「签名」一节。
    val keystore = file("shiyi.jks")
    signingConfigs {
        if (keystore.exists()) {
            create("selfsigned") {
                storeFile = keystore
                storePassword = System.getenv("SHIYI_KEYSTORE_PASSWORD") ?: "shiyiarchive"
                keyAlias = System.getenv("SHIYI_KEY_ALIAS") ?: "shiyi"
                keyPassword = System.getenv("SHIYI_KEY_PASSWORD") ?: "shiyiarchive"
            }
        }
    }

    buildTypes {
        debug {
            isMinifyEnabled = false
        }
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"),
                          "proguard-rules.pro")
            signingConfig = signingConfigs.findByName("selfsigned")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures { compose = true; buildConfig = true }
    packaging {
        resources.excludes += setOf("/META-INF/{AL2.0,LGPL2.1}", "META-INF/*.version")
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2024.12.01")
    implementation(composeBom)

    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.7")
    implementation("androidx.documentfile:documentfile:1.0.1")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")

    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-graphics")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    implementation("androidx.compose.animation:animation")

    debugImplementation("androidx.compose.ui:ui-tooling")
    implementation("androidx.compose.ui:ui-tooling-preview")
}
