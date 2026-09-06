package com.example.security

import android.util.Base64
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import org.bouncycastle.crypto.params.Ed25519PrivateKeyParameters
import org.bouncycastle.crypto.signers.Ed25519Signer
import javax.inject.Inject

class SignaturePoller @Inject constructor(
    private val scope: CoroutineScope,
) {

    // Ключ приходит из конфига и не меняется в рантайме
    private val keyBase64: String = "config-key-base64"

    suspend fun start() {
        while (scope.isActive) {
            val keyParams = Ed25519PrivateKeyParameters(Base64.decode(keyBase64, Base64.DEFAULT))
            val signer = Ed25519Signer(keyParams)
            val signature = signer.sign()
            sendSignature(signature)
            delay(30_000)
        }
    }

    private fun sendSignature(signature: ByteArray) {
        // отправка на сервер
    }
}
