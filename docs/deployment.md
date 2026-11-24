# Docker Hub and EC2 deployment

Publish five service images to one Docker Hub repository, then pull them on EC2.
For repository `yourusername/retail` and release `1.0.1`, the tags are:

```text
yourusername/retail:auth-1.0.1
yourusername/retail:agent-1.0.1
yourusername/retail:domain-1.0.1
yourusername/retail:frontend-1.0.1
yourusername/retail:gateway-1.0.1
```

PostgreSQL uses `postgres:17-alpine`. The maintenance job reuses the Domain image.
The database contents and server secrets are separate from the images.

The default setup uses an SSH tunnel to access the internal application. Step 10
also describes access at the instance's public IP for a temporary HTTP demo.

## 1. Prepare Docker Hub and your computer

Start Docker Desktop using Linux containers. Create a repository named `retail`
under your Docker Hub account. Use private visibility if the image contents should
remain private. Your account/token needs push access locally and pull access on
EC2 for a private repository.

Open **local Windows PowerShell** in the application directory (the inner
directory containing `compose.yaml`):

```powershell
cd E:\GradClass\Learning\Online\BeaconfireAssignment\retail-internal-ai-agent\retail-internal-ai-agent

$DockerUser = "YOUR_DOCKERHUB_USERNAME"
$DockerImage = "${DockerUser}/retail"
$Release = "1.0.1"

docker version
docker buildx version
docker login --username $DockerUser
```

Use the same repository name and release throughout these steps. The examples
build `linux/amd64` images for an x86_64 EC2 instance.

## 2. Build and push all five tags

Run these in **local PowerShell**. This loop stops on a failed build/push:

```powershell
$Builds = @(
  @{ Service = "auth";     Dockerfile = "auth/Dockerfile";             Context = "." },
  @{ Service = "agent";    Dockerfile = "agent/Dockerfile";            Context = "." },
  @{ Service = "domain";   Dockerfile = "domain/Dockerfile";           Context = "." },
  @{ Service = "frontend"; Dockerfile = "frontend/Dockerfile";        Context = "./frontend" },
  @{ Service = "gateway";  Dockerfile = "platform/gateway/Dockerfile"; Context = "./platform/gateway" }
)

foreach ($Build in $Builds) {
  $Image = "${DockerImage}:$($Build.Service)-${Release}"
  docker buildx build --platform linux/amd64 --file $Build.Dockerfile --tag $Image --push $Build.Context
  if ($LASTEXITCODE -ne 0) {
    throw "Build/push failed for $Image. Correct the error before continuing."
  }
}
```

Confirm all five tags in the repository's Docker Hub **Tags** tab. Backend
contexts are the repository root so their images include `shared/`. Frontend API
URLs default to the same origin, with mocks disabled. No EC2 address or API key
is required at frontend build time. Never pass runtime secrets as build arguments.
For a corporate CA, see [platform build instructions](../platform/README.md).

Image naming and publication follow the
[Docker Hub publishing documentation](https://docs.docker.com/docker-hub/repos/manage/hub-images/push/).

## 3. Package the server configuration

Run in **local PowerShell**, using the same `$Release`:

```powershell
$Bundle = "retail-deploy-${Release}.tar.gz"
tar -czf $Bundle compose.yaml compose.registry.yaml compose.ec2-http.yaml deploy/ec2.env.example platform/postgres
if ($LASTEXITCODE -ne 0) { throw "Deployment bundle creation failed." }
tar -tzf $Bundle
```

The explicit file list includes PostgreSQL initialization scripts and the new
environment template. Your local `.env`, database, and backend source are not
included. `compose.registry.yaml` removes all build definitions from the merged
configuration, so source/build contexts are unnecessary on EC2. All health
checks, dependencies, runtime configuration, and the named data volume come from
the base Compose file. Runtime containers restart automatically and rotate logs.

## 4. Launch EC2 and transfer the bundle

In the AWS EC2 console, launch an instance with:

| Setting | Value |
| --- | --- |
| AMI | Ubuntu Server 24.04 LTS |
| Architecture | x86_64 / amd64 |
| Instance size | Start with 2 vCPUs and at least 4 GiB RAM for the demo |
| Storage | Start with 30 GiB encrypted gp3 |
| Network | Public subnet, internet gateway route, public IPv4 address |
| Key pair | A key whose private `.pem` file you have locally |
| Inbound security group | TCP 22 from your current public IP only |

Sizing is an initial estimate; inspect actual resource use after startup.
Leave application and database ports closed for the tunnel setup. Outbound access
must allow package downloads, Docker Hub pulls, and the Agent's external API
calls. The usual default outbound rules permit this. Do not open ports 5432 or
8000 to the internet. See [AWS security groups](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-security-groups.html).

In **local PowerShell**, replace both placeholders:

```powershell
$KeyFile = "C:\path\retail-key.pem"
$Ec2Address = "EC2_PUBLIC_IP"

# Restrict this private key to the Windows account running SSH.
$CurrentSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
icacls.exe $KeyFile /inheritance:r /grant:r "*${CurrentSid}:(R)"
if ($LASTEXITCODE -ne 0) { throw "Could not restrict private key permissions." }

scp -i $KeyFile $Bundle "ubuntu@${Ec2Address}:/home/ubuntu/"
ssh -i $KeyFile "ubuntu@${Ec2Address}"
```

This removes inherited access and grants your account read access. It fixes
Windows OpenSSH's `UNPROTECTED PRIVATE KEY FILE` / `bad permissions` error when
the unwanted access rules are inherited. If the error persists, inspect
`icacls.exe $KeyFile` for explicit permissions belonging to other accounts and
remove those permissions from this key file. See the
[AWS private key permissions troubleshooting instructions](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/TroubleshootingInstancesConnecting.html).
Keep the key out of Git; `.pem` files are excluded by the root `.gitignore`.

Verify the SSH host fingerprint through a trusted AWS source on first connection.

## 5. Install Docker on EC2

Run in the **EC2 SSH session**, using a fresh Ubuntu 24.04 installation:

```bash
sudo apt update
sudo apt install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker ubuntu
exit
```

Reconnect from **local PowerShell**:

```powershell
ssh -i $KeyFile "ubuntu@${Ec2Address}"
```

Verify inside **EC2**:

```bash
docker version
docker compose version
```

Use Compose 2.24.4 or later, including current v5 releases. Reconnecting applies
the Docker group membership. These installation commands follow the
[official Ubuntu Docker instructions](https://docs.docker.com/engine/install/ubuntu/).

## 6. Unpack and configure EC2

On **EC2**, replace the bundle filename if using a different release:

```bash
mkdir -p ~/retail
cd ~/retail
tar -xzf ~/retail-deploy-1.0.1.tar.gz
if [ ! -f .env ]; then
  cp deploy/ec2.env.example .env
fi
chmod 600 .env
nano .env
```

Set `DOCKERHUB_IMAGE=YOUR_DOCKERHUB_USERNAME/retail` and `IMAGE_TAG=1.0.1`.
Retain `APP_ENV=demo`: the Agent's settings accept only `local`, `ci`, and `demo`.
Using `production` prevents the Agent from starting. Compose configuration
validation checks the Compose model; application settings are validated at startup.
Replace every credential placeholder: `POSTGRES_PASSWORD`, `AUTH_DB_PASSWORD`,
`DOMAIN_DB_PASSWORD`, `AGENT_DB_PASSWORD`, `JWT_SECRET`,
`INTERNAL_SERVICE_TOKEN`, `SEED_ANALYST_PASSWORD`, and `SEED_VIEWER_PASSWORD`.
Generate a different random value for each secret, for example by running
`openssl rand -hex 32` separately for each value. The JWT secret must contain at
least 32 bytes. Store the login passwords securely.

Set `ANTHROPIC_API_KEY` to a working key and ensure `ANTHROPIC_MODEL` is available
to your provider account. Optional Langfuse tracing is disabled in this template;
set the keys and enable it if wanted. Leave optional migration/evaluation login
passwords blank unless needed.

For the default SSH tunnel, retain:

```dotenv
APP_PORT=18080
COOKIE_SECURE=false
PUBLIC_ORIGIN=http://localhost:18081
SEED_AUTH_ACCOUNTS=true
```

The browser will use localhost HTTP, carried through an encrypted SSH connection.
An HTTPS deployment must use `COOKIE_SECURE=true` and its HTTPS public origin.
Protect and back up the server's `.env`; preserve database passwords during
upgrades. Auth seeding preserves existing account passwords, so editing a seed
password later does not change an existing account password.

## 7. Pull and initialize a fresh demo database

Run **on EC2**. Define this helper again whenever you open a new SSH session:

```bash
cd ~/retail
dc() {
  docker compose -f compose.yaml -f compose.registry.yaml "$@"
}
```

Authenticate for private repositories (also useful for authenticated public pulls):

```bash
docker login --username YOUR_DOCKERHUB_USERNAME
dc config --quiet
dc --profile maintenance pull
```

Run the following **one command at a time, continuing only after success**:

```bash
dc up -d --no-build --wait --wait-timeout 180 postgres
dc exec -T postgres sh /setup/provision.sh
dc run --rm --no-deps demo-reset
dc exec -T postgres sh /setup/provision.sh
dc up -d --no-build --wait --wait-timeout 180
```

**Use this initialization sequence only for a fresh/disposable demo database.**
`demo-reset` clears Agent history and reseeds Domain business and evaluation data.
It preserves Auth accounts. For a rerun against a disposable database, first stop
`gateway`, `agent`, and `domain`. Use step 11 for updates that preserve data.
API startup alone does not apply Domain migrations or seed the demo dataset.

The maintenance profile makes its image available for pulling. Normal startup
does not run maintenance jobs. Use these deployment commands on EC2; the local
`make up`/`make reset` targets intentionally build images.

## 8. Verify the running stack

On **EC2**:

```bash
dc ps
curl --fail --show-error http://127.0.0.1:18080/health
curl --fail --show-error http://127.0.0.1:18080/auth/ready
curl --fail --show-error http://127.0.0.1:18080/domain/ready
curl --fail --show-error http://127.0.0.1:18080/agent/health
```

Each endpoint should return HTTP 200. Then verify an authenticated browser login
and an investigation to exercise the model provider. Health checks alone do not
prove external model access.

If startup or requests fail:

```bash
dc logs --tail=100 postgres auth domain agent gateway
docker stats --no-stream
df -h
```

Common causes include an incorrect image/tag, missing pull access, a credential
placeholder, unavailable model access, incomplete migrations, or insufficient
memory/disk. If provisioning failed during first database startup, inspect the
Postgres logs and rerun provisioning after the server is running; existing data
directories skip automatic initialization scripts.

## 9. Open the app through SSH

In another **local PowerShell** window (define these variables there if needed):

```powershell
$KeyFile = "C:\path\retail-key.pem"
$Ec2Address = "EC2_PUBLIC_IP"
ssh -i $KeyFile -o ExitOnForwardFailure=yes -N -L 18081:127.0.0.1:18080 "ubuntu@${Ec2Address}"
```

Keep the command running and open [http://localhost:18081](http://localhost:18081).
Log in as `analyst` or `viewer` using your configured EC2 seed password.
If local port 18081 is already occupied, choose another local tunnel port and
update `PUBLIC_ORIGIN` on EC2 to match, then recreate Auth with `dc up -d auth`.

## 10. Optional: access the EC2 public IP over HTTP

Use release `1.0.1` or later for this mode. It fixes a browser error in `1.0.0`
that prevented login requests on public HTTP pages by requiring `crypto.randomUUID`.
The frontend now shares a UUID helper with a `crypto.getRandomValues` fallback.

For a temporary demo, allow inbound TCP 80 **from your IP** in the EC2 security
group. On EC2, change `.env` to `PUBLIC_ORIGIN=http://EC2_PUBLIC_IP` with the actual
address; retain `COOKIE_SECURE=false` for HTTP. Include a port in the origin if
you choose a non-default `HTTP_PORT`.

Redefine the helper to include the optional HTTP override:

```bash
cd ~/retail
dc() {
  docker compose -f compose.yaml -f compose.registry.yaml -f compose.ec2-http.yaml "$@"
}
dc config --quiet
dc up -d --no-build --wait --wait-timeout 180
```

Open `http://EC2_PUBLIC_IP`. The override replaces the localhost binding with
port 80 on the host. Use `http://127.0.0.1/health` and matching port-80 API URLs
for server checks in this mode. The SSH tunnel from step 9 targets port 18080
and applies only to the default configuration.

Compose's `!override` replaces the ports list rather than adding a second
binding; see the [Compose merge reference](https://docs.docker.com/reference/compose-file/merge/).

For shared access, configure a domain and TLS reverse proxy or an HTTPS load
balancer, set `PUBLIC_ORIGIN=https://your-domain` and `COOKIE_SECURE=true`, and
restrict gateway ingress to the intended proxy/load balancer. This optional
file configures HTTP only. An Elastic IP or domain avoids relying on a public
address that can change after an instance stop/start.

## 11. Deploy later releases while preserving data

Publish all five tags using a new release such as `1.0.2`; retain earlier release
tags. Recreate and transfer the matching deployment bundle if configuration or
PostgreSQL provisioning scripts changed. Extract it into `~/retail` without
replacing the existing `.env`. Update only `IMAGE_TAG` and any intentionally
changed settings. Keep the same directory/project name and database volume.

On EC2, define `dc` using the same files as your active deployment, including
`compose.ec2-http.yaml` if using public HTTP. Before changing the running stack,
make a database backup and copy it to separate storage:

```bash
cd ~/retail
dc exec -T postgres sh -c \
  'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > "backup-$(date +%Y%m%d-%H%M%S).dump"
```

Check that the backup command succeeded. This is a database backup; service-role
setup is supplied by the provisioning scripts. Retain a protected copy of `.env`
as well.

Run each command only after the preceding command succeeds:

```bash
dc config --quiet
dc --profile maintenance pull
dc stop gateway agent domain
dc up -d --no-build --wait --wait-timeout 180 postgres
dc exec -T postgres sh /setup/provision.sh
dc run --rm --no-deps demo-reset python -m alembic -c domain/alembic.ini upgrade head
dc exec -T postgres sh /setup/provision.sh
dc up -d --no-build --wait --wait-timeout 180
dc ps
```

The explicit Alembic command replaces the maintenance service's destructive
default reset command. Rerun health checks and a browser login afterward.
If a migration fails, leave the stopped services offline while diagnosing it.
Reverting image tags alone is safe only if the database schema remains compatible
with the earlier application; otherwise a planned restore/migration is needed.

`dc down` removes containers while preserving the database volume. **`dc down -v`
deletes that volume.** The volume survives container restarts and ordinary EC2
reboots, but it is stored on the instance's EBS disk and is not a backup. This
single-instance setup has downtime during maintenance and no high availability.
