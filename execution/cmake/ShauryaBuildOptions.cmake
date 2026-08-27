option(SHAURYA_ENABLE_LIVE_ROUTER "Compile network-capable live order routing" OFF)
option(SHAURYA_WARNINGS_AS_ERRORS "Treat compiler warnings as errors" OFF)

if(SHAURYA_ENABLE_LIVE_ROUTER)
  message(FATAL_ERROR
    "LIVE ROUTING REFUSED: this delivery has no live authority; "
    "SHAURYA_ENABLE_LIVE_ROUTER must remain OFF"
  )
endif()

set(SHAURYA_LIVE_ROUTER_ATTESTATION "off")
