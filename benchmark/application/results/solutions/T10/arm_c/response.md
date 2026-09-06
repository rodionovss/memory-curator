```diff
diff --git a/app.kt b/app.kt
index 60b05bc..85e51be 100644
--- a/app.kt
+++ b/app.kt
@@ -1,5 +1,5 @@
 package com.example
 
 fun main() {
-    println("app v1")
+    println("app v2 modified")
 }
diff --git a/new_module.kt b/new_module.kt
new file mode 100644
index 0000000..31e6644
--- /dev/null
+++ b/new_module.kt
@@ -0,0 +1,6 @@
+package com.example
+
+fun newFeature(): String {
+    // MARKER_153_UNTRACKED_CONTENT
+    return "new"
+}
```
