# OpenOCD Common Board / Interface / Target Configuration Quick Reference

OpenOCD describes the debug chain through combinations of `.cfg` configuration files. Prefer using `board` configurations (which already include interface and target); otherwise, manually combine `interface + target`.

## Interface (Debug Adapters)

| Debugger Type | Configuration File |
|---------------|-------------------|
| ST-Link V2 | `interface/stlink.cfg` |
| ST-Link V3 | `interface/stlink.cfg` |
| CMSIS-DAP | `interface/cmsis-dap.cfg` |
| DAPLink | `interface/cmsis-dap.cfg` |
| J-Link | `interface/jlink.cfg` |
| FTDI Series | `interface/ftdi/minimodule.cfg`, etc. |

## Target (Target MCUs / SoCs)

### STMicroelectronics

| Family | Configuration File |
|--------|-------------------|
| STM32F0 | `target/stm32f0x.cfg` |
| STM32F1 | `target/stm32f1x.cfg` |
| STM32F2 | `target/stm32f2x.cfg` |
| STM32F3 | `target/stm32f3x.cfg` |
| STM32F4 | `target/stm32f4x.cfg` |
| STM32F7 | `target/stm32f7x.cfg` |
| STM32G0 | `target/stm32g0x.cfg` |
| STM32G4 | `target/stm32g4x.cfg` |
| STM32H7 | `target/stm32h7x.cfg` |
| STM32L0 | `target/stm32l0x.cfg` |
| STM32L1 | `target/stm32l1x.cfg` |
| STM32L4 | `target/stm32l4x.cfg` |
| STM32U5 | `target/stm32u5x.cfg` |
| STM32WB | `target/stm32wbx.cfg` |
| STM32WL | `target/stm32wlx.cfg` |

### GigaDevice

| Family | Configuration File |
|--------|-------------------|
| GD32F1x3 | `target/stm32f1x.cfg` (compatible) |
| GD32F3x0 | `target/stm32f1x.cfg` (compatible) |
| GD32F4xx | `target/stm32f4x.cfg` (compatible) |
| GD32E103 | `target/stm32f1x.cfg` (compatible) |

> GigaDevice MCUs are typically compatible with the corresponding STM32 family target configurations.

### Nordic Semiconductor

| Family | Configuration File |
|--------|-------------------|
| nRF51 | `target/nrf51.cfg` |
| nRF52 | `target/nrf52.cfg` |

### NXP

| Family | Configuration File |
|--------|-------------------|
| LPC1768 | `target/lpc1768.cfg` |
| LPC4088 | `target/lpc4088.cfg` |

### ESP32

| Family | Configuration File |
|--------|-------------------|
| ESP32 | `target/esp32.cfg` |
| ESP32-S2 | `target/esp32s2.cfg` |
| ESP32-S3 | `target/esp32s3.cfg` |
| ESP32-C3 | `target/esp32c3.cfg` |

## Board (Development Boards, includes interface + target)

| Board | Configuration File |
|-------|-------------------|
| STM32F4 Discovery | `board/stm32f4discovery.cfg` |
| STM32F429 Discovery | `board/stm32f429disc1.cfg` |
| STM32F746 Discovery | `board/stm32f746g-disco.cfg` |
| STM32 Nucleo-F401RE | `board/st_nucleo_f4.cfg` |
| STM32 Nucleo-L476RG | `board/st_nucleo_l476rg.cfg` |
| nRF52-DK | `board/nordic_nrf52_dk.cfg` |

## Finding Full List

If your target is not listed above, find it via:

1. Listing OpenOCD built-in configurations: `ls <openocd-scripts-dir>/target/`
2. Searching official OpenOCD documentation: https://openocd.org/doc-release/html/index.html
3. Testing combinations by running: `openocd -f interface/stlink.cfg -f target/stm32f4x.cfg -c "init; targets; shutdown"`
