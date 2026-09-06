package com.example.di

import androidx.lifecycle.ViewModel
import kotlin.reflect.KClass
import dagger.MapKey

@MustBeDocumented
@Target(AnnotationTarget.FUNCTION, AnnotationTarget.CLASS)
@Retention(AnnotationRetention.RUNTIME)
@MapKey
annotation class ViewModelKey(val value: KClass<out ViewModel>)
