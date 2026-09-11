// 国内网络：阿里云镜像优先，官方源兜底。
// 这份仓库列表和 c30/FocusLock 保持一致——本机 Gradle 缓存是被那个工程
// 填起来的，列表不一致会让 Gradle 绕开缓存去重新下载，然后卡在 TLS 握手。
pluginManagement {
    repositories {
        maven { url = uri("https://maven.aliyun.com/repository/google") }
        maven { url = uri("https://maven.aliyun.com/repository/gradle-plugin") }
        maven { url = uri("https://maven.aliyun.com/repository/central") }
        google()
        gradlePluginPortal()
        mavenCentral()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        maven { url = uri("https://maven.aliyun.com/repository/google") }
        maven { url = uri("https://maven.aliyun.com/repository/central") }
        google()
        mavenCentral()
    }
}

// 工程名保持 ASCII：Gradle 的中间产物路径带中文会炸成 Invalid file path。
// 用户看到的名字在 res/values/strings.xml 里。
rootProject.name = "shiyi-android"
include(":app")
