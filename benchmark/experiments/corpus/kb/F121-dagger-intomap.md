---
type: Reference
tags: [dagger, viewmodel, multibindings]
---

# Dagger-карта ViewModel требует @IntoMap + ключ

Multibindings-карта ViewModelFactory наполняется только через @Provides-метод
с @IntoMap и ключом @ViewModelKey(КонкретныйViewModel::class). Без @IntoMap
провайдер не попадает в map: на рантайме падение Unknown ViewModel из
ViewModelFactory.create.
