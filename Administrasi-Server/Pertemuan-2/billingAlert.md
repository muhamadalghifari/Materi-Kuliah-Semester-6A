# Membuat Billing Alert di AWS untuk menghindari kelebihan alokasi Dana

1. Menu Dashboard AWS kita pilih Billing Preference untuk mengaktifkan Alert
 - masuk Menu Billing and Cost Management
 - Pada Menu Cost Management Scroll ke bawah pilih Billing Preferences
 - Pilih menu Alert Preferences klik Edit
 - isi Email ceklis Receive 
 - Klik Update

 ![alt text](image-2.png)
 ![alt text](image-3.png)

 2. Masuk Menu Cloudwatch, All Services Pilih CLoudWatch

 3. Pilih Menu Create Alarm
  - Pastikan Region ada di US N Virginia
  - Klik Menu Create ALert
  - Klik Metric
  - Klik Menu Billing
  - Pilih Menu Total Estimated Charge
  - Pilih / Ceklis Mata Uang USD
  - Klik Select Metric
  - beri nama Alert = NIM_BillingAlert
  - COnditions Static->Greathertha-> 1 USD
  - Create new Topic = > NIM_BillingAlert -> Klik Create
  - Select an existing SNS topic - > NIM_BillingAlert
  - Klik Next
  - Alarm Name -> NIM_BillingAlert
  - Create Alarm
  - Buka Inbox/Spam Email dari AWS kemudian Klik Confirm

 ![alt text](image-4.png)

 