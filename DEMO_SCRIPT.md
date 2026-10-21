# EduMesh teacher demo script

This is a simple three-person presentation. It takes about 6 to 8 minutes.

## Before the demo

1. Open [http://65.1.146.176](http://65.1.146.176) using **HTTP**.
2. Keep the AWS Console or terminal ready only if the teacher asks for proof.
3. Prepare these example questions:
   - `Explain supervised learning in machine learning.`
   - `What is database normalization?`
   - `Explain Kubernetes pods and services.`

## Person 1 — Project introduction and website (about 2 minutes)

Say:

> Good morning. Our project is EduMesh. It is a learning assistant for three
> subjects: Machine Learning, DBMS, and Cloud Computing. A student can type one
> question, and the system finds which subject service understands it best.

Show the website and type the ML example question.

Say:

> We do not send every question directly to one fixed service. First, all three
> services check the question. The system chooses the service with the best
> score. Here, ML wins because the question is about supervised learning.

Show the generated answer.

Then say:

> The same website can answer DBMS and Cloud questions. This makes the project
> a small distributed system, not just one single program.

## Person 2 — Docker and Kubernetes (about 2 to 3 minutes)

Say:

> We divided the application into four Docker containers: Gateway, ML, DBMS,
> and Cloud. Docker makes the application run in the same way on our laptop and
> on AWS.

Show `docker-compose.yml` or the diagram in `README.md`.

Say:

> Kubernetes runs these containers on AWS. The Gateway receives the student
> question. ML, DBMS, and Cloud are separate services. Kubernetes monitors the
> containers and restarts a subject service if it stops.

Say:

> We tested this by deleting the ML Kubernetes pod. Kubernetes automatically
> created a new healthy ML pod in around 12 seconds. So one failed subject
> container does not stop the complete project.

Then say:

> We also added automatic scaling for load. ML, DBMS, and Cloud each normally
> have one pod. Kubernetes checks their CPU separately. If one subject reaches
> 70 percent CPU, only that subject can automatically increase to two pods.
> Kubernetes then shares that subject's requests between its two pods.

Show `k8s/app.yaml` and point out that it is kept in one file to make the
deployment easy to understand. Point out `minReplicas: 1`, `maxReplicas: 2`,
and `averageUtilization: 70` in the HPA section.

### Optional live proof of automatic scaling

Open AWS **Systems Manager** → **Run Command** → **AWS-RunShellScript**.
Select the `edumesh-k3s` EC2 instance and run:

```bash
sudo k3s kubectl get hpa -n edumesh
sudo k3s kubectl top pods -n edumesh
```

Show the `TARGETS` column. For example, `cpu: 4%/70%` means Kubernetes is
measuring the service, its current CPU use is 4 percent, and it will add a
second pod only if it reaches 70 percent. The `MINPODS 1` and `MAXPODS 2`
columns prove the allowed automatic range.

Say:

> At the moment the services are not overloaded, so Kubernetes correctly keeps
> one pod for each subject. The autoscaler is active and ready. When a specific
> subject crosses 70 percent CPU, it alone can scale to two pods.

## Person 3 — AWS and serverless part (about 2 minutes)

Say:

> Our application is hosted on AWS. We use EC2 to run K3s Kubernetes. Amazon
> ECR stores our Docker image. AWS Parameter Store keeps API keys encrypted, so
> keys are not written in the source code or Docker image.

Say:

> We also use AWS Lambda for audio transcription. Lambda is serverless, which
> means AWS runs it only when audio transcription is requested. We do not need
> to keep a separate transcription server running all the time.

Say:

> Therefore, our design is hybrid: Kubernetes and Docker run the main
> distributed application, while Lambda handles the short audio task.

End with:

> In summary, EduMesh shows service routing, Docker containers, Kubernetes
> self-healing, AWS hosting, secure key storage, and serverless Lambda in one
> simple student project.

## If the teacher asks questions

**Why not use only Lambda?**

> Kubernetes and Docker were required for this project. Lambda is used where it
> makes the most sense: short transcription requests.

**What happens if ML stops?**

> Kubernetes restarts ML automatically. Until it is ready, the Gateway can
> still ask DBMS and Cloud.

**How do you handle an overloaded subject?**

> Kubernetes HPA watches ML, DBMS, and Cloud separately. When one subject uses
> 70 percent CPU, only that subject can automatically grow from one to two
> pods. The internal Kubernetes Service distributes its requests between them.

**Do you use an AWS Load Balancer?**

> Not for this small assignment. We have one EC2 machine, so an AWS Load
> Balancer would have only one server to send traffic to. Kubernetes Services
> already distribute requests between replicas inside this server. A production
> version with multiple EC2 machines would add an AWS Load Balancer.

**Why use Parameter Store?**

> It stores API keys securely in AWS instead of exposing them in source code.

**Why is the public link HTTP?**

> The demonstration deployment currently uses HTTP. HTTPS and a domain can be
> added later for public microphone support.
