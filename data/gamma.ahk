#Requires AutoHotkey v2.0
#SingleInstance Force
Persistent

; ============================================================================
; NVIDIA GAMMA TOGGLE
; AutoHotkey v2
;
; F10        -> Toggle high gamma on/off
; Shift + F9 -> Emergency gamma reset
;
; Runs as administrator (it asks once when started) so the keys also work
; while Rust has focus.
; ============================================================================


; ============================================================================
; RUN AS ADMINISTRATOR
; ============================================================================

fullCommandLine := DllCall("GetCommandLine", "Str")

if !(A_IsAdmin || RegExMatch(fullCommandLine, " /restart(?!\S)"))
{
    try
    {
        if A_IsCompiled
            Run('*RunAs "' A_ScriptFullPath '" /restart')
        else
            Run('*RunAs "' A_AhkPath '" /restart "' A_ScriptFullPath '"')
    }

    ExitApp
}


; ============================================================================
; CONFIGURATION
; ============================================================================

; Keys use AutoHotkey names: F10, XButton1 (mouse 4), +F9 (Shift + F9)...
TOGGLE_KEY := "F10"
RESET_KEY  := "+F9"

NORMAL_GAMMA := 1.00
HIGH_GAMMA   := 2.80

TOOLTIP_DURATION := 900

gammaEnabled := false


; ============================================================================
; INITIALIZE NVIDIA NVAPI
; ============================================================================

NV := InitNvApi()

if !IsObject(NV)
{
    MsgBox(
        "Failed to initialize NVIDIA NVAPI.`n`n"
        . "Make sure the display is connected to the NVIDIA GPU.",
        "NVIDIA Gamma",
        "Iconx"
    )

    ExitApp
}


; ============================================================================
; HOTKEYS
; ============================================================================

Hotkey(TOGGLE_KEY, ToggleGamma)
Hotkey(RESET_KEY, ResetGamma)


; ----------------------------------------------------------------------------
; Toggle high gamma
; ----------------------------------------------------------------------------

ToggleGamma(*)
{
    global gammaEnabled
    global NORMAL_GAMMA
    global HIGH_GAMMA
    global NV

    targetGamma := gammaEnabled
        ? NORMAL_GAMMA
        : HIGH_GAMMA

    if !SetNvGamma(NV, targetGamma)
    {
        MsgBox(
            "NVIDIA rejected the gamma change.",
            "NVIDIA Gamma",
            "Iconx"
        )

        return
    }

    gammaEnabled := !gammaEnabled

    if gammaEnabled
        ShowStatus("Gamma: HIGH (" Format("{:.2f}", HIGH_GAMMA) ")")
    else
        ShowStatus("Gamma: NORMAL (" Format("{:.2f}", NORMAL_GAMMA) ")")
}


; ----------------------------------------------------------------------------
; Emergency reset
; ----------------------------------------------------------------------------

ResetGamma(*)
{
    global gammaEnabled
    global NORMAL_GAMMA
    global NV

    if !SetNvGamma(NV, NORMAL_GAMMA)
    {
        MsgBox(
            "NVIDIA rejected the gamma reset.",
            "NVIDIA Gamma",
            "Iconx"
        )

        return
    }

    gammaEnabled := false

    ShowStatus(
        "Gamma: RESET (" Format("{:.2f}", NORMAL_GAMMA) ")"
    )
}


; ============================================================================
; NVAPI INITIALIZATION
; ============================================================================

InitNvApi()
{
    ; Load NVIDIA NVAPI.
    hNvApi := DllCall(
        "kernel32\LoadLibraryW",
        "Str", "nvapi64.dll",
        "Ptr"
    )

    if !hNvApi
        return false


    ; Retrieve nvapi_QueryInterface.
    queryInterface := DllCall(
        "kernel32\GetProcAddress",
        "Ptr", hNvApi,
        "AStr", "nvapi_QueryInterface",
        "Ptr"
    )

    if !queryInterface
        return false


    ; ------------------------------------------------------------------------
    ; NvAPI_Initialize
    ;
    ; Interface ID:
    ; 0x0150E828
    ; ------------------------------------------------------------------------

    nvInitialize := GetNvApiFunction(
        queryInterface,
        0x0150E828
    )

    if !nvInitialize
        return false


    status := DllCall(
        nvInitialize,
        "Int"
    )

    if (status != 0)
        return false


    ; ------------------------------------------------------------------------
    ; NvAPI_DISP_GetGDIPrimaryDisplayId
    ;
    ; Retrieves the NVIDIA display ID corresponding to the primary
    ; Windows GDI display.
    ; ------------------------------------------------------------------------

    getPrimaryDisplay := GetNvApiFunction(
        queryInterface,
        0x1E9D8A31
    )

    if !getPrimaryDisplay
        return false


    displayIdBuffer := Buffer(4, 0)

    status := DllCall(
        getPrimaryDisplay,
        "Ptr", displayIdBuffer.Ptr,
        "Int"
    )

    if (status != 0)
        return false


    displayId := NumGet(
        displayIdBuffer,
        0,
        "UInt"
    )


    ; ------------------------------------------------------------------------
    ; NvAPI_DISP_SetTargetGammaCorrection
    ;
    ; This function is not part of NVIDIA's publicly documented NVAPI,
    ; but it is exposed by some driver versions and can be used to modify
    ; the hardware gamma ramp directly.
    ; ------------------------------------------------------------------------

    setGamma := GetNvApiFunction(
        queryInterface,
        0x7082A053
    )

    if !setGamma
    {
        MsgBox(
            "This NVIDIA driver does not expose the required "
            . "gamma correction function.",
            "NVIDIA Gamma",
            "Iconx"
        )

        return false
    }


    return Map(
        "Library",        hNvApi,
        "QueryInterface", queryInterface,
        "DisplayId",      displayId,
        "SetGamma",       setGamma
    )
}


; ============================================================================
; NVAPI FUNCTION LOOKUP
; ============================================================================

GetNvApiFunction(queryInterface, interfaceId)
{
    if !queryInterface
        return 0

    return DllCall(
        queryInterface,
        "UInt", interfaceId,
        "Ptr"
    )
}


; ============================================================================
; APPLY NVIDIA GAMMA
; ============================================================================

SetNvGamma(nv, gamma)
{
    if !IsObject(nv)
        return false

    if !nv.Has("SetGamma")
        return false

    if !nv.Has("DisplayId")
        return false


    ; Prevent invalid or dangerous values.
    if (gamma <= 0.0)
        return false


    gammaRamp := BuildGammaRamp(gamma)

    if !IsObject(gammaRamp)
        return false


    try
    {
        status := DllCall(
            nv["SetGamma"],
            "UInt", nv["DisplayId"],
            "Ptr", gammaRamp.Ptr,
            "Int"
        )

        return status = 0
    }
    catch
    {
        return false
    }
}


; ============================================================================
; BUILD GAMMA RAMP
; ============================================================================

BuildGammaRamp(gamma)
{
    ; ------------------------------------------------------------------------
    ; Internal NVAPI gamma correction structure.
    ;
    ; Layout:
    ;
    ; UInt  version
    ; Float gammaRamp[1024][3]
    ; UInt  flags
    ;
    ; Size:
    ;
    ; 4 bytes
    ; + 1024 samples * 3 channels * 4 bytes
    ; + 4 bytes
    ;
    ; = 12296 bytes
    ; ------------------------------------------------------------------------

    static RAMP_POINTS      := 1024
    static CHANNELS         := 3
    static FLOAT_SIZE       := 4

    static HEADER_SIZE      := 4
    static STRUCTURE_SIZE   := 12296
    static FLAGS_OFFSET     := 12292

    static STRUCT_VERSION   := 0x13008


    ramp := Buffer(
        STRUCTURE_SIZE,
        0
    )


    ; NVAPI structure version.
    NumPut(
        "UInt",
        STRUCT_VERSION,
        ramp,
        0
    )


    ; ------------------------------------------------------------------------
    ; Generate the gamma curve.
    ;
    ; Normal gamma:
    ;
    ;     y = x
    ;
    ; Modified gamma:
    ;
    ;     y = x ^ (1 / gamma)
    ;
    ; Each RGB channel receives the same value so that only luminance
    ; changes while preserving the color balance.
    ; ------------------------------------------------------------------------

    Loop RAMP_POINTS
    {
        index := A_Index - 1

        x := index / (RAMP_POINTS - 1.0)

        value := (index = 0)
            ? 0.0
            : x ** (1.0 / gamma)


        baseOffset :=
            HEADER_SIZE
            + (index * CHANNELS * FLOAT_SIZE)


        ; Red
        NumPut(
            "Float",
            value,
            ramp,
            baseOffset
        )


        ; Green
        NumPut(
            "Float",
            value,
            ramp,
            baseOffset + FLOAT_SIZE
        )


        ; Blue
        NumPut(
            "Float",
            value,
            ramp,
            baseOffset + (FLOAT_SIZE * 2)
        )
    }


    ; Required structure flag.
    NumPut(
        "UInt",
        1,
        ramp,
        FLAGS_OFFSET
    )


    return ramp
}


; ============================================================================
; STATUS NOTIFICATION
; ============================================================================

ShowStatus(text)
{
    global TOOLTIP_DURATION

    ToolTip(text)

    SetTimer(
        HideStatus,
        -TOOLTIP_DURATION
    )
}


HideStatus()
{
    ToolTip()
}
