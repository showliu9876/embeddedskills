# Common Chip Device Name Reference Table

Chip model names used in J-Link Commander (case-sensitive).

## STMicroelectronics

| Series | Example Device Names |
|------|----------------|
| STM32F0 | STM32F030R8, STM32F072RB |
| STM32F1 | STM32F103C8, STM32F103RB, STM32F103ZE |
| STM32F2 | STM32F207VG, STM32F207ZG |
| STM32F3 | STM32F303CC, STM32F303VC |
| STM32F4 | STM32F401RE, STM32F407VG, STM32F429ZI |
| STM32F7 | STM32F746ZG, STM32F767ZI |
| STM32G0 | STM32G030K8, STM32G071RB |
| STM32G4 | STM32G431KB, STM32G474RE |
| STM32H7 | STM32H743ZI, STM32H750VB |
| STM32L0 | STM32L053R8, STM32L073RZ |
| STM32L1 | STM32L151RB, STM32L152RE |
| STM32L4 | STM32L431RC, STM32L476RG |
| STM32U5 | STM32U575ZI, STM32U585AI |
| STM32WB | STM32WB55RG |
| STM32WL | STM32WLE5JC |

## GigaDevice

| Series | Example Device Names |
|------|----------------|
| GD32F1 | GD32F103C8, GD32F130G8 |
| GD32F3 | GD32F303CC, GD32F350RB |
| GD32F4 | GD32F407VG, GD32F450ZI |
| GD32E1 | GD32E103C8, GD32E230C8 |
| GD32E5 | GD32E507ZE |

## Nordic Semiconductor

| Series | Example Device Names |
|------|----------------|
| nRF51 | nRF51822_xxAA |
| nRF52 | nRF52832_xxAA, nRF52840_xxAA |
| nRF53 | nRF5340_xxAA_APP, nRF5340_xxAA_NET |
| nRF91 | nRF9160_xxAA |

## NXP

| Series | Example Device Names |
|------|----------------|
| LPC | LPC1768, LPC54608J512 |
| i.MX RT | MIMXRT1052xxx5B, MIMXRT1062xxx5A |
| Kinetis | MK64FN1M0xxx12 |

## Microchip (Atmel)

| Series | Example Device Names |
|------|----------------|
| SAM | ATSAMD21G18, ATSAME70Q21 |

## Finding the Complete List

If the target chip is not listed in the tables above, search via the following methods:

1. Open J-Link Commander and enter `ExpDevList` to view the full list.
2. Search the SEGGER Wiki: https://wiki.segger.com/Supported_devices
3. Use the `JLinkExe` command with the `-device ?` argument to list all supported devices.
