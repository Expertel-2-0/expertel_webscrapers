# PROD Deployment Status — expertel_webscrapers

**Fecha:** 2026-04-28
**Ambiente objetivo:** prod (us-east-2, AWS Account 741340773091)
**Branch:** qa (cambios pendientes de commit)

---

## 1. Resumen ejecutivo

El proyecto `expertel_webscrapers` ya tenía estructura de carpetas para `dev`, `qa` y `prod`, pero la configuración de **PROD estaba desactualizada** respecto a QA y, además, las dependencias del lado del **backend (`experteliq`) en producción no existen todavía en AWS**. Antes de poder desplegar el scraper a prod hay que:

1. Que el equipo del backend despliegue primero `experteliq2-backend-prod` (VPC, security group `app-sg`, y los SSM `/config/app-settings` + `/config/alb-url`).
2. Crear el key pair `experteliq2-prod-key` en EC2.
3. Crear el bucket S3 `experteliq2-scraper-terraform-state-prod`.
4. Cargar los secretos del scraper en SSM con `manage-secrets.sh setup prod`.

Una vez hecho lo anterior, los archivos `plan-prod.sh` / `deploy-prod.sh` (ya actualizados) ejecutan exactamente el mismo flujo que QA contra los SSM de backend prod.

---

## 2. Cómo se conecta el scraper a la base de datos (QA y PROD)

### Flujo en QA (validado contra AWS)

```
experteliq2-backend-qa (Terraform)
    ├─ Crea VPC                         tag:Name = experteliq2-backend-qa-vpc
    ├─ Crea security group               tag:Name = experteliq2-backend-qa-app-sg
    ├─ Crea EC2 con Postgres+Mongo
    └─ Publica SSM:
         /experteliq2-backend/qa/config/app-settings   (String JSON)
              { db_host, db_port, db_name, db_user, mongodb_host, ... }
         /experteliq2-backend/qa/config/alb-url        (String)

expertel_webscrapers (Terraform, env=qa)
    ├─ data.aws_vpc.backend            -> filtra tag:Name = "{backend_app}-{env}-vpc"
    ├─ data.aws_subnets.public         -> public-subnet-* del VPC del backend
    ├─ data.aws_security_group         -> app-sg del backend (la EC2 del scraper se mete a esa SG
    │                                     para tener acceso a la BD)
    ├─ data.aws_ssm_parameter.backend_app_settings
    │       value = jsondecode(...)    -> de aquí salen db_host, db_port, db_name, db_user
    ├─ data.aws_ssm_parameter.backend_url -> URL del ALB del backend
    └─ Crea EC2 scraper en subnet pública del backend, con la SG del backend adjunta,
       y publica:
         /experteliq2-scraper/qa/database/host
         /experteliq2-scraper/qa/database/name
         /experteliq2-scraper/qa/database/port
         /experteliq2-scraper/qa/database/username
         /experteliq2-scraper/qa/database/password (SecureString, manual via manage-secrets.sh)
         /experteliq2-scraper/qa/backend-api/url
         ...
```

El user_data.sh de la EC2 del scraper lee todos esos SSM al arrancar y arma el `.env` de la app. La BD se alcanza por **IP privada dentro de la VPC del backend** (no hay ruteo público a Postgres/Mongo).

### Flujo previsto en PROD (idéntico, sólo cambian valores)

`environment = "prod"` → Terraform busca `experteliq2-backend-prod-vpc`, `experteliq2-backend-prod-app-sg`, `/experteliq2-backend/prod/config/app-settings`, `/experteliq2-backend/prod/config/alb-url`. **Hoy ninguno de esos recursos existe** (ver auditoría AWS más abajo), por eso no se puede correr `terraform plan` de prod aún.

---

## 3. Cambios aplicados en este PR (sólo en `expertel_webscrapers`)

### 3.1 Terraform `environments/prod/`

| Archivo | Cambio |
|---|---|
| `03-data.tf` | **Reescrito** para leer `data.aws_ssm_parameter.backend_app_settings` (JSON) y parsearlo con `jsondecode(...)`, igual que QA. Antes leía un SSM `/database/host` que **no lo crea el backend**, así que el plan habría fallado. |
| `30-ssm.tf` | Ahora publica `db_host`, `db_name`, `db_port`, `db_username` desde `local.db_*` (vienen del JSON), no desde valores hardcodeados. Se corrigió `email_host = "smtp.your-provider.com"` (placeholder de `.env.example`) → `smtp.office365.com` para igualar a QA. `backend_url` ya no antepone `http://` porque el SSM `alb-url` del backend ya lo trae. |
| `00-versions.tf` | Sin cambios. Backend S3 apunta a `experteliq2-scraper-terraform-state-prod` (bucket que aún no existe). |
| `01-locals.tf`, `02-variables.tf`, `10-notifications.tf`, `20-compute.tf`, `40-codebuild.tf`, `90-outputs.tf` | Sin cambios. Ya estaban bien. Diferencias intencionales vs QA: `key_name = experteliq2-prod-key`, `github_branch = master`, `enable_webhook = false` (toggleable), `create_elastic_ip = true` (IP estable para prod). |

### 3.2 Scripts shell

| Archivo | Cambio |
|---|---|
| `deployment/aws/plan-prod.sh` | **Reescrito** con la misma estructura de `plan-qa.sh` (chequea terraform + AWS, banner de PROD, `terraform init && plan`). Antes era una versión mínima sin checks. |
| `deployment/aws/deploy-prod.sh` | **Reescrito** con la misma estructura de `deploy-qa.sh` (validate secrets → init → plan → confirmación explícita "yes" → apply → muestra outputs). Mantiene el banner de PRODUCTION. |
| `deployment/aws/manage-secrets.sh` | Sin cambios. Ya soporta `prod` por argumento, mismo registro de secretos para todos los ambientes. |

### 3.3 Scripts PowerShell

Migración completa a paridad con los `.sh` (un wrapper por ambiente, además del script parametrizado base).

| Archivo | Cambio |
|---|---|
| `deployment/windows/Plan-Environment.ps1` | **Creado** (faltaba). Acepta `-Environment dev|qa|prod`. Espejo de `plan-*.sh`. |
| `deployment/windows/Plan-Dev.ps1` | **Creado**. Wrapper que invoca `Plan-Environment.ps1 -Environment dev`. Espejo de `plan-dev.sh`. |
| `deployment/windows/Plan-QA.ps1` | **Creado**. Wrapper a `Plan-Environment.ps1 -Environment qa`. Espejo de `plan-qa.sh`. |
| `deployment/windows/Plan-Prod.ps1` | **Creado**. Wrapper a `Plan-Environment.ps1 -Environment prod`. Espejo de `plan-prod.sh`. |
| `deployment/windows/Deploy-Environment.ps1` | Sin cambios. Acepta `-Environment dev|qa|prod` y `-AutoApprove`. |
| `deployment/windows/Deploy-Dev.ps1` | **Creado**. Wrapper a `Deploy-Environment.ps1 -Environment dev`. Soporta `-AutoApprove`. Espejo de `deploy-dev.sh`. |
| `deployment/windows/Deploy-QA.ps1` | **Creado**. Wrapper a `Deploy-Environment.ps1 -Environment qa`. Soporta `-AutoApprove`. Espejo de `deploy-qa.sh`. |
| `deployment/windows/Deploy-Prod.ps1` | **Creado**. Wrapper a `Deploy-Environment.ps1 -Environment prod`. **NO** acepta `-AutoApprove` (siempre exige confirmación 'yes'). Espejo de `deploy-prod.sh`. |
| `deployment/windows/Manage-Secrets.ps1` | Sin cambios. Acepta `-Environment dev|qa|prod`. |
| `deployment/windows/Setup-Secrets-Dev.ps1` | **Creado**. Wrapper a `Manage-Secrets.ps1 -Command setup -Environment dev`. Sube TODAS las variables de entorno (env vars / secretos) a SSM. |
| `deployment/windows/Setup-Secrets-QA.ps1` | **Creado**. Igual para QA. |
| `deployment/windows/Setup-Secrets-Prod.ps1` | **Creado**. Igual para PROD. **Este es el script para subir variables de entorno a producción.** |
| `deployment/windows/Validate-Secrets-Dev.ps1` | **Creado**. Wrapper a `Manage-Secrets.ps1 -Command validate -Environment dev`. Verifica que todas las requeridas existan en SSM. |
| `deployment/windows/Validate-Secrets-QA.ps1` | **Creado**. Igual para QA. |
| `deployment/windows/Validate-Secrets-Prod.ps1` | **Creado**. Igual para PROD. |

### 3.4 Módulos Terraform

`deployment/aws/terraform/modules/scraper-instance/`, `notifications/`, `codebuild/`: **sin cambios**. Son agnósticos al ambiente y se reusan.

### 3.5 `buildspec.yml`

Sin cambios. Es agnóstico al ambiente; CodeBuild recibe `ENVIRONMENT`, `INSTANCE_ID` y `GITHUB_BRANCH` por variables del proyecto (que crea el módulo `codebuild` en cada env).

---

## 4. Auditoría AWS (us-east-2, cuenta 741340773091)

### 4.1 VPCs existentes
```
vpc-007c83133fa205b02  10.10.0.0/16   experteliq2-backend-rabbitmq-vpc
vpc-0238201ce49a106c3  10.1.0.0/16    experteliq2-backend-qa-vpc
```
**No existe** `experteliq2-backend-prod-vpc`.

### 4.2 Security groups
```
sg-0687d461e357a509b   experteliq2-backend-qa-app-sg
```
**No existe** `experteliq2-backend-prod-app-sg`.

### 4.3 SSM parameters del backend prod
```
/experteliq2-backend/prod/rabbitmq/host
/experteliq2-backend/prod/rabbitmq/password
/experteliq2-backend/prod/rabbitmq/port
/experteliq2-backend/prod/rabbitmq/url
/experteliq2-backend/prod/rabbitmq/user
/experteliq2-backend/prod/rabbitmq/vhost
```
**Sólo está el RabbitMQ compartido.** Faltan `/config/app-settings` y `/config/alb-url`, que es lo que el scraper consume. (Comparativa: QA tiene 20 parámetros incluyendo todos los de DB, Django, email, etc.)

### 4.4 Key pairs EC2
```
experteliq2-qa-key
```
**No existe** `experteliq2-prod-key`.

### 4.5 Buckets S3 relevantes
```
experteliq2-scraper-terraform-state-qa     <- existe
experteliq2-terraform-state-prod           <- backend prod (existe)
experteliq2-terraform-state-shared
```
**No existe** `experteliq2-scraper-terraform-state-prod` (lo necesita `00-versions.tf` del scraper prod).

### 4.6 Instancias EC2 del scraper
```
i-08ebe6169cea107b3  running   experteliq2-scraper-qa-scraper
```
Sólo QA. PROD aún sin instancia (lo cual es lo esperado).

---

## 5. ¿Estamos listos para desplegar a producción?

**No todavía.** Faltan dependencias externas que están fuera del alcance de este repo. La parte del scraper en sí (Terraform + scripts) ya está alineada con QA y lista para correr en cuanto se cumplan los prerequisitos.

### 5.1 Bloqueadores (orden de resolución)

| # | Bloqueador | Quién | Comando / Acción |
|---|---|---|---|
| 1 | Backend prod no desplegado (sin VPC, sin app-sg, sin SSM `/config/*`) | Equipo backend (`experteliq`) | Desplegar `experteliq/deployment/aws/terraform/environments/prod/` (revisar también `terraform.tfvars` que tiene varios `TODO`: `db_host`, `mongodb_host`, `certificate_arn`, `route53_zone_id`). |
| 2 | EC2 key pair `experteliq2-prod-key` no existe | Ops/devops | `aws ec2 create-key-pair --key-name experteliq2-prod-key --region us-east-2 --query "KeyMaterial" --output text > experteliq2-prod-key.pem` (guardar el .pem en lugar seguro). |
| 3 | Bucket S3 para tfstate del scraper prod no existe | Ops/devops | `aws s3 mb s3://experteliq2-scraper-terraform-state-prod --region us-east-2` y luego habilitar versioning. |
| 4 | Secretos del scraper prod en SSM no existen (validate -> 8 required missing) | Tú | `cd deployment/aws && ./manage-secrets.sh setup prod` (o `Manage-Secrets.ps1 -Command setup -Environment prod`). |

### 5.2 Pasos para desplegar (después de resolver los bloqueadores)

```bash
cd C:/Users/Alejandro/Documents/GitHub/Expertel/expertel_webscrapers/deployment/aws

# 1. validar secretos
./manage-secrets.sh validate prod

# 2. plan (revisar diff)
./plan-prod.sh

# 3. apply (te pedirá escribir 'yes' explícito)
./deploy-prod.sh
```

Equivalente Windows (atajos por ambiente):
```powershell
cd C:\Users\Alejandro\Documents\GitHub\Expertel\expertel_webscrapers\deployment\windows

# 0. (una sola vez) subir variables de entorno / secretos a SSM
.\Setup-Secrets-Prod.ps1

# 1. validar que estén todas
.\Validate-Secrets-Prod.ps1

# 2. plan
.\Plan-Prod.ps1

# 3. apply (te pedirá escribir 'yes' explícito, NO admite -AutoApprove)
.\Deploy-Prod.ps1
```

Forma parametrizada equivalente (la que ya existía):
```powershell
.\Manage-Secrets.ps1   -Command setup    -Environment prod
.\Manage-Secrets.ps1   -Command validate -Environment prod
.\Plan-Environment.ps1                   -Environment prod
.\Deploy-Environment.ps1                 -Environment prod
```

### 5.3 Después del primer apply

- Subir webhook de GitHub: cambiar `enable_webhook = true` en `02-variables.tf` (prod) y volver a `apply`. CodeBuild expondrá un webhook que se pega en `Settings → Webhooks` del repo, branch `master`.
- Activar Elastic IP ya viene en `true` para prod (`20-compute.tf`), así que la IP pública no cambia entre redeploys.

---

## 6. Diferencias QA vs PROD (intencionales)

| Setting | QA | PROD |
|---|---|---|
| `key_name` | `experteliq2-qa-key` | `experteliq2-prod-key` |
| `github_branch` | `qa` | `master` |
| `enable_webhook` | `true` | `false` (encender después del primer deploy) |
| `create_elastic_ip` | `false` | `true` |
| `frontend_url` | ALB de QA (`http://experteliq2-frontend-qa-alb-...`) | `https://app.expertel.com` |
| `scraper_alert_emails` | `nelson@expertel.com` | `nelson@expertel.com` (igual; cambiar si prod debe avisar a más gente) |
| Backend SSM target | `/experteliq2-backend/qa/...` | `/experteliq2-backend/prod/...` |
| S3 tfstate bucket | `experteliq2-scraper-terraform-state-qa` | `experteliq2-scraper-terraform-state-prod` |

Todo lo demás (módulos, IAM, SNS, CodeBuild, user_data, schedule timer, secretos esperados) es idéntico.

---

## 7. Cobertura de variables de entorno (matriz `.env` ↔ SSM ↔ código)

Se hizo una auditoría 1:1 del `.env` real de QA contra:
- el código (`os.environ.get` / `os.getenv` en todo el repo),
- el registry de secretos (`manage-secrets.sh` / `Manage-Secrets.ps1`),
- los SSM no-secretos generados por Terraform (`30-ssm.tf`),
- y el `user_data.sh` que arma el `.env` en la EC2.

### 7.1 Gaps encontrados y corregidos en este pase

| Variable | Antes | Ahora |
|---|---|---|
| `TWO_CAPTCHA_API_KEY` | Estaba en `.env` de QA pero **no** se subía a SSM ni se rehidrataba en la EC2. | Agregada como **secreto opcional** al registry: `/experteliq2-scraper/{env}/two-captcha/api-key`. user_data.sh ahora la lee y la escribe al `.env`. |
| `CAPSOLVER_API_KEY` | Igual que arriba (la lib `capsolver-extension-python` está en `pyproject.toml`). | Agregada como **secreto opcional**: `/experteliq2-scraper/{env}/capsolver/api-key`. user_data.sh la lee y la escribe al `.env`. |
| `SCRAPER_EXECUTION_LOG_EMAILS` | **Usada** en `config/settings.py:167` (cae al default `alejandro@expertel.com`), pero no estaba en SSM, ni en registry, ni en user_data.sh, ni en `.env`. | Agregada como SSM **no-secreto** generado por Terraform: `/experteliq2-scraper/{env}/email/execution-log-recipients`. user_data.sh la escribe al `.env`. |
| `.env.example` | Sólo describía un subconjunto y tenía placeholders confusos (`smtp.your-provider.com`). | Reescrito como referencia completa, indicando para cada variable la ruta SSM correspondiente. |

### 7.2 Matriz final (cubre el 100% del `.env` que el scraper consume)

| Variable | Origen | SSM path | Cómo se carga |
|---|---|---|---|
| DB_HOST | Backend (JSON `app-settings`) | `/experteliq2-scraper/{env}/database/host` | terraform 30-ssm.tf |
| DB_NAME | Backend (JSON `app-settings`) | `/experteliq2-scraper/{env}/database/name` | terraform 30-ssm.tf |
| DB_PORT | Backend (JSON `app-settings`) | `/experteliq2-scraper/{env}/database/port` | terraform 30-ssm.tf |
| DB_USERNAME | Backend (JSON `app-settings`) | `/experteliq2-scraper/{env}/database/username` | terraform 30-ssm.tf |
| DB_PASSWORD | Manual (Secret) | `/experteliq2-scraper/{env}/database/password` | manage-secrets.sh (R) |
| EIQ_BACKEND_API_BASE_URL | Backend (`alb-url`) | `/experteliq2-scraper/{env}/backend-api/url` | terraform 30-ssm.tf |
| EIQ_BACKEND_API_KEY | Manual (Secret) | `/experteliq2-scraper/{env}/backend-api/key` | manage-secrets.sh (R) |
| CRYPTOGRAPHY_KEY | Manual (Secret) | `/experteliq2-scraper/{env}/cryptography/key` | manage-secrets.sh (R) |
| CLIENT_ID | Manual (Plain) | `/experteliq2-scraper/{env}/azure/client-id` | manage-secrets.sh (R) |
| TENANT_ID | Manual (Plain) | `/experteliq2-scraper/{env}/azure/tenant-id` | manage-secrets.sh (R) |
| CLIENT_SECRET | Manual (Secret) | `/experteliq2-scraper/{env}/azure/client-secret` | manage-secrets.sh (R) |
| USER_EMAIL | Hardcoded `notifications@expertel.com` | `/experteliq2-scraper/{env}/azure/user-email` | terraform 30-ssm.tf |
| ANTHROPIC_API_KEY | Manual (Secret, Optional) | `/experteliq2-scraper/{env}/anthropic/api-key` | manage-secrets.sh (O) |
| GEMINI_API_KEY | Manual (Secret, Optional) | `/experteliq2-scraper/{env}/gemini/api-key` | manage-secrets.sh (O) |
| **TWO_CAPTCHA_API_KEY** | Manual (Secret, Optional) | `/experteliq2-scraper/{env}/two-captcha/api-key` | manage-secrets.sh (O) — **NUEVO** |
| **CAPSOLVER_API_KEY** | Manual (Secret, Optional) | `/experteliq2-scraper/{env}/capsolver/api-key` | manage-secrets.sh (O) — **NUEVO** |
| MFA_SERVICE_URL | Hardcoded `http://localhost:7000` | `/experteliq2-scraper/{env}/mfa-service/url` | terraform 30-ssm.tf |
| EMAIL_HOST | `smtp.office365.com` | `/experteliq2-scraper/{env}/email/host` | terraform 30-ssm.tf |
| EMAIL_PORT | `587` | `/experteliq2-scraper/{env}/email/port` | terraform 30-ssm.tf |
| EMAIL_HOST_USER | Manual (Plain, Optional) | `/experteliq2-scraper/{env}/email/host-user` | manage-secrets.sh (O) |
| EMAIL_HOST_PASSWORD | Manual (Secret, Optional) | `/experteliq2-scraper/{env}/email/host-password` | manage-secrets.sh (O) |
| EMAIL_USE_TLS | `True` | `/experteliq2-scraper/{env}/email/use-tls` | terraform 30-ssm.tf |
| EMAIL_FROM_ADDRESS | `iqnotifications@expertel.com` | `/experteliq2-scraper/{env}/email/from-address` | terraform 30-ssm.tf |
| SCRAPER_ALERT_EMAILS | `nelson@expertel.com` | `/experteliq2-scraper/{env}/email/alert-recipients` | terraform 30-ssm.tf |
| **SCRAPER_EXECUTION_LOG_EMAILS** | `alejandro@expertel.com` | `/experteliq2-scraper/{env}/email/execution-log-recipients` | terraform 30-ssm.tf — **NUEVO** |
| FRONTEND_URL | env-specific | `/experteliq2-scraper/{env}/config/frontend-url` | terraform 30-ssm.tf |
| NOVNC_PASSWORD | Manual (Secret) | `/experteliq2-scraper/{env}/novnc/password` | manage-secrets.sh (R) — para chpasswd, no va al `.env` |
| ENVIRONMENT | Terraform var | n/a | user_data.sh (variable plantilla) |
| SNS_TOPIC_ARN | Output del módulo notifications | n/a | user_data.sh (variable plantilla) |
| Slack/Teams webhooks | Manual (Secret, Optional) | `/experteliq2-scraper/{env}/{slack,teams}/webhook-url` | usados por la lambda de notificaciones, no por el scraper |

> R = Required, O = Optional, en el registry de `manage-secrets.sh`.

Tras estos cambios, **todas las variables del `.env` real de QA tienen ruta SSM declarada y se rehidratan automáticamente** en la EC2 al hacer `Setup-Secrets-{env}.ps1` + `Deploy-{env}.ps1`. No queda ninguna variable suelta.

---

## 8. Archivos que toqué en este pase

```
deployment/aws/terraform/environments/prod/03-data.tf      (rewrite)
deployment/aws/terraform/environments/prod/30-ssm.tf       (rewrite)
deployment/aws/plan-prod.sh                                (rewrite)
deployment/aws/deploy-prod.sh                              (rewrite)

# Paridad PS1 ↔ SH por ambiente (todos nuevos)
deployment/windows/Plan-Environment.ps1                    (new — base parametrizado)
deployment/windows/Plan-Dev.ps1                            (new)
deployment/windows/Plan-QA.ps1                             (new)
deployment/windows/Plan-Prod.ps1                           (new)
deployment/windows/Deploy-Dev.ps1                          (new)
deployment/windows/Deploy-QA.ps1                           (new)
deployment/windows/Deploy-Prod.ps1                         (new)
deployment/windows/Setup-Secrets-Dev.ps1                   (new — sube env vars a SSM)
deployment/windows/Setup-Secrets-QA.ps1                    (new — sube env vars a SSM)
deployment/windows/Setup-Secrets-Prod.ps1                  (new — sube env vars a SSM)
deployment/windows/Validate-Secrets-Dev.ps1                (new)
deployment/windows/Validate-Secrets-QA.ps1                 (new)
deployment/windows/Validate-Secrets-Prod.ps1               (new)

# Cobertura completa de variables de entorno
deployment/aws/manage-secrets.sh                           (registry: + two-captcha, + capsolver)
deployment/windows/Manage-Secrets.ps1                      (registry: + two-captcha, + capsolver)
deployment/aws/terraform/environments/dev/30-ssm.tf        (+ execution-log-recipients)
deployment/aws/terraform/environments/qa/30-ssm.tf         (+ execution-log-recipients)
deployment/aws/terraform/environments/prod/30-ssm.tf       (+ execution-log-recipients)
deployment/aws/terraform/modules/scraper-instance/templates/user_data.sh
                                                           (lee y escribe al .env: TWO_CAPTCHA_API_KEY,
                                                            CAPSOLVER_API_KEY, SCRAPER_EXECUTION_LOG_EMAILS)
.env.example                                               (rewrite como referencia completa con SSM paths)

PROD_DEPLOYMENT_STATUS.md                                  (this file)
```

No se ejecutó ningún `terraform apply` ni `aws ssm put-parameter`. Sólo lecturas de inventario contra AWS para validar el estado actual.
