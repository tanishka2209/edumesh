# EduMesh

EduMesh is a simple learning website that answers questions from three subjects:

- Machine Learning (ML)
- Database Management Systems (DBMS)
- Cloud Computing

When a student asks a question, all three subject services check it. The service
that understands the topic best gives the answer. For example, a question about
neural networks goes to ML, while a question about normalization goes to DBMS.

## How it works

```text
Student browser
       |
    Gateway
  /    |    \
ML   DBMS   Cloud
       |
 Groq AI answers
```

The Gateway is the entry point. It asks every subject service, compares their
scores, and selects the best one. Each subject service has its own topic list.
Answers are generated using Groq.

## AWS architecture

The live project uses a practical hybrid architecture:

```text
Internet
   |
AWS EC2 server
   |
K3s Kubernetes
   |-- Gateway Docker container
   |-- ML Docker container
   |-- DBMS Docker container
   `-- Cloud Docker container

AWS Lambda: audio transcription
AWS ECR: Docker image storage
AWS Parameter Store: encrypted API keys
```

Kubernetes keeps the services running. If one subject container stops, K3s
automatically creates a replacement. The Gateway can still use the other
subjects when one service is unavailable.

The transcription part is serverless because it runs with AWS Lambda. The main
application is containerized and runs on Kubernetes, so this is a hybrid
container + serverless project.

## Live application

Open: [http://65.1.146.176](http://65.1.146.176)

Use `http`, not `https`, at the moment. Text questions work publicly. Browser
microphone recording needs HTTPS and a domain, so it works locally but is not
yet available on the public HTTP URL.

## Run locally with Docker

1. Create `.env` from `.env.example` and add your Groq and Deepgram keys.
2. Start the project:

```bash
docker compose up --build
```

3. Open [http://localhost:18400](http://localhost:18400).

Stop it with:

```bash
docker compose down
```

## Important files

| File or folder | Purpose |
| --- | --- |
| `gateway.py` | Receives questions and chooses the best subject service. |
| `service.py` | Runs one ML, DBMS, or Cloud subject service. |
| `lexicons.py` | Topic words used to decide which service understands a question. |
| `index.html` | Website user interface. |
| `Dockerfile` | Instructions to create the Docker image. |
| `docker-compose.yml` | Runs all four services locally. |
| `run.sh` | Starts the same four services directly with Python, without Docker. |
| `k8s/app.yaml` | The complete simple Kubernetes deployment file. |
| `lambda_transcribe.py` | AWS Lambda code for audio transcription. |
| `transcription_client.py` | Lets the Gateway call the transcription Lambda. |
| `deploy/aws/` | AWS roles, launch-template, and EC2 bootstrap templates. |
| `tests/test_transcription.py` | Tests for audio transcription safety and fallback behavior. |

## Testing

Run the transcription tests with:

```bash
python -m unittest discover -s tests -v
```

The project has been tested with local Docker, live Kubernetes pods, public
health checks, subject routing, Lambda activation, and Kubernetes self-healing.

## AWS cost reminder

The EC2 server is running and uses AWS credits or billing. Stop or terminate
the `edumesh-k3s` EC2 instance when the project is not needed. Stopping it
makes the public website unavailable until it is started again.

## Load handling and failure handling

### If one subject service is busy or overloaded

The Gateway sends the question to ML, DBMS, and Cloud at the same time. It
waits only a short time for each service. If one service is slow, the Gateway
can still use a fast response from the other services instead of making the
whole website wait.

Each Kubernetes container also has CPU and memory limits. This prevents one
subject service from using all resources on the EC2 server and affecting every
other service. On the current small single-server deployment, very high load
can still make answers slower because all containers share one EC2 machine.

Each subject also has a Horizontal Pod Autoscaler (HPA). It normally keeps one
ML, DBMS, and Cloud pod. If one subject's average CPU usage reaches 70%, only
that subject can automatically grow to two pods. Its Kubernetes Service shares
requests between the two pods. When load falls, Kubernetes returns it to one
pod.

To demonstrate that it is active, open AWS Systems Manager → Run Command and
run these commands on `edumesh-k3s`:

```bash
sudo k3s kubectl get hpa -n edumesh
sudo k3s kubectl top pods -n edumesh
```

The `TARGETS` value, for example `cpu: 4%/70%`, proves that HPA is reading CPU
usage. `MINPODS 1`, `MAXPODS 2`, and `REPLICAS 1` show that the service is
healthy at normal load and may create one extra copy when required.

### If one subject container stops

K3s Kubernetes detects that the container is no longer healthy and creates a
new replacement container automatically. We tested this by deleting the ML
pod; Kubernetes created a healthy replacement in about 12 seconds. While ML
is restarting, the Gateway can still contact DBMS and Cloud.

### If the whole EC2 server goes down

The current setup has one EC2 server, so the public website becomes unavailable
until that server is restarted or replaced. This is acceptable for a small
student project and keeps AWS cost low.

For a larger production version, we would use two or more EC2/Kubernetes nodes
in different availability zones, put a load balancer in front of them, and add
automatic scaling. That would handle much higher load and keep the project
online even if one complete server fails.
