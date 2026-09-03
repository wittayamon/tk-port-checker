<p align="right">
  <a href="README.md">
    <img src="https://img.shields.io/badge/Language-English-blue?style=for-the-badge">
  </a>
  <a href="README_TH.md">
    <img src="https://img.shields.io/badge/ภาษา-ไทย-green?style=for-the-badge">
  </a>
</p>

# Multi Host Port Checker

แอปพลิเคชันเดสก์ท็อป Tkinter สำหรับ Windows ที่ใช้ตรวจสอบค่าความหน่วงของ ICMP Ping และสถานะการเชื่อมต่อ TCP Port ของเป้าหมายรายตัวหรือช่วง IPv4

ผลลัพธ์ของ Ping และ TCP แยกจากกัน: Host อาจตอบสนองต่อ Ping แต่ TCP Port ที่กำหนดอาจ offline หรือ Host อาจบล็อก Ping แต่บริการ TCP ยังคง online

[![Download EXE](https://img.shields.io/badge/Download-MultiPortChecker.exe-brightgreen?style=for-the-badge)](https://github.com/wittayamon/tk-port-checker/releases/latest/download/MultiPortChecker.exe)

## ความสามารถ

- เพิ่มและลบเป้าหมาย Host/IP + TCP Port
- ตรวจสอบ Ping หนึ่งครั้ง โดยแสดงค่าความหน่วง, `Timeout` หรือค่าสำรอง `Online`
- ตรวจสอบ TCP Port ด้วย socket พร้อมแสดงสถานะ ONLINE/OFFLINE ด้วยสี
- Check Selected และ Check All
- Auto Refresh ที่ไม่ทำงานซ้อนกัน
- ตรวจสอบในพื้นหลังด้วย worker pool แบบจำกัดขนาด ทำให้ UI ตอบสนองได้ตลอด
- IPv4 Range Scan พร้อมความคืบหน้าและการยกเลิก
- เลือกแสดง IP ที่สแกนทั้งหมดได้
- แถว Host/IP + Port ที่ซ้ำกันจะถูกอัปเดตแทนการเพิ่มใหม่
- Windows Trace Route แบบ streaming พร้อมกำหนดจำนวน hop และเวลารอการตอบกลับได้
- บันทึกและโหลดรายการ Host ในรูปแบบ JSON
- โหลด Host ที่บันทึกไว้และการตั้งค่า theme โดยอัตโนมัติ
- Theme แบบ Dark และ Light
- การจัดการ icon และ resource ที่รองรับ PyInstaller

## IPv4 Range Scan

กรอก Start IP, End IP และ TCP Port สำหรับช่วงที่รวมทั้งค่าเริ่มต้นและสิ้นสุด จากนั้นเลือก **Scan** ตัวอย่าง:

```text
Start IP: 192.168.1.1
End IP:   192.168.1.254
Port:     443
```

ป้ายความคืบหน้าจะแสดงค่าเช่น `Scanning 37 / 254` ปุ่ม **Cancel Scan** จะหยุดส่งที่อยู่ใหม่ทันทีและยกเลิกงานที่รออยู่ ส่วนการเรียกใช้งานเครือข่ายที่เริ่มทำงานแล้วจะได้รับอนุญาตให้ทำงานจนเสร็จอย่างปลอดภัย

โดยค่าเริ่มต้น การสแกนจะเพิ่มหรืออัปเดตเฉพาะเป้าหมายที่ตอบสนองต่อ Ping หรือมี TCP Port เปิดอยู่ เปิดใช้ **Show all scanned IPs** เพื่อแสดงผลลัพธ์ Ping-timeout/TCP-offline ด้วย แถวที่ค้นพบใหม่จากการสแกนเป็นผลลัพธ์ runtime และจะไม่ถูกเขียนลง config ของแอปโดยอัตโนมัติเมื่อปิดแอป ใช้ **Save List** หากต้องการส่งออกแถวที่แสดงอยู่โดยตั้งใจ

ช่วงจะต้องประกอบด้วยที่อยู่ IPv4 ที่ถูกต้อง End IP ต้องไม่ต่ำกว่า Start IP และการสแกนจำกัดไว้ที่ 1,024 ที่อยู่ ให้หยุด Auto Refresh และรอให้การตรวจสอบที่กำลังทำงานเสร็จก่อนเริ่ม IP Range Scan

## Trace Route

เลือกแถว Host/IP เพียงหนึ่งแถวและเลือก **Trace Route** หน้าต่างแยกที่ปรับขนาดได้จะรันการ trace และแสดง output ดิบของ `tracert` ที่ทยอยส่งมา รองรับทั้งที่อยู่ IPv4 และ DNS hostname เช่น `google.com`

คำสั่งเริ่มต้นคือ:

```powershell
tracert -d -h 15 -w 1000 <host>
```

- `-d` ปิดการค้นหา DNS hostname ของ hop ระหว่างทาง ซึ่งช่วยหลีกเลี่ยงความล่าช้าจากการค้นหา
- **Max Hops** มีค่าเริ่มต้น 15 และรับค่าได้ตั้งแต่ 1 ถึง 255
- **Timeout** คือเวลารอต่อการตอบกลับหนึ่งครั้งในหน่วยมิลลิวินาที มีค่าเริ่มต้น 1000 ms และรับค่าได้ตั้งแต่ 1 ถึง 60000 ms
- **Run Again** ล้าง output และเริ่ม trace ใหม่ด้วยค่าขีดจำกัดปัจจุบัน
- **Stop** ยุติ trace ที่กำลังทำงาน, **Copy** คัดลอก output ปัจจุบันทั้งหมด และ **Close** หยุด trace ที่กำลังทำงานอย่างปลอดภัยก่อนปิดหน้าต่าง

Ping, สถานะ TCP และ Trace Route เป็นสัญญาณวินิจฉัยที่แยกจากกัน hop ที่ timeout (`* * *`) ไม่ได้พิสูจน์ว่าปลายทางหรือบริการ TCP offline เนื่องจาก router ระหว่างทางอาจไม่สนใจข้อความ ICMP TTL-expired ผล Trace จะไม่เปลี่ยนสถานะ ONLINE/OFFLINE ในตาราง

## คอลัมน์สถานะ

```text
Host / IP | Port | Ping (ms) | Status
```

- ค่า Ping อาจเป็น `7 ms`, `<1 ms`, `Timeout` หรือ `Online` หาก Ping สำเร็จแต่ไม่สามารถแยกค่าความหน่วงได้
- ONLINE/OFFLINE แสดงสถานะของ TCP Port เสมอ ไม่ใช่สถานะ Ping

## ข้อกำหนด

- Python 3.9 หรือใหม่กว่าเมื่อรันจาก source
- เป้าหมายหลักคือ Windows 10/11
- ไม่มี dependency ภายนอกสำหรับ runtime

## การรันจาก source

```powershell
python -m venv venv
venv\Scripts\activate
python multi_port_checker.py
```

## ข้อมูลที่บันทึก

รายการ Host ยังคงเข้ากันได้กับรูปแบบเดิม:

```json
{
  "host": "google.com",
  "port": 443
}
```

ค่าความหน่วงของ Ping และสถานะ TCP เป็นค่า runtime และไม่จำเป็นต้องมีในไฟล์ที่บันทึก

## การสร้าง Windows EXE

ติดตั้ง PyInstaller ใน build environment แล้วใช้ spec file ที่ track ไว้:

```powershell
pyinstaller --noconfirm MultiPortChecker.spec
```

ไฟล์ที่รันได้จะถูกสร้างที่ `dist\MultiPortChecker.exe` เครื่องปลายทางไม่จำเป็นต้องติดตั้ง Python

## โครงสร้างโปรเจกต์

```text
multi_port_checker.py       Tkinter UI and background task coordination
network_checks.py           Ping, TCP, IPv4 validation, and scan-plan helpers
test_ping_helpers.py        Ping/TCP helper tests
test_range_scan_helpers.py  IPv4 range, duplicate-key, and cancellation tests
test_trace_route_helpers.py Trace command and input-validation tests
MultiPortChecker.spec       PyInstaller build configuration
icon_network_transparent.ico
README.md
README_TH.md
changelog.md
```

## การทดสอบ

```powershell
python -m unittest -v
python -m py_compile multi_port_checker.py network_checks.py test_ping_helpers.py test_range_scan_helpers.py test_trace_route_helpers.py
```

## แผนงานในอนาคต

- รองรับ System tray
- การแจ้งเตือนเมื่อบริการที่เฝ้าติดตามเปลี่ยนสถานะ
- การบันทึกสถานะไปยังภายนอก
