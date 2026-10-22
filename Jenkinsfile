// ModeraGuard CI/CD pipeline (owner: M6)
//
// Every push to main:   lint -> tests -> data checks -> train + quality gate
//                       -> build images -> Trivy scan -> push -> canary deploy (10%)
// Run with parameters to move the canary on:
//   DEPLOY_MODE=set-weight CANARY_WEIGHT=50    shift more traffic to the canary
//   DEPLOY_MODE=promote                        challenger becomes champion, canary removed
//   DEPLOY_MODE=rollback                       canary removed, champion untouched
//   DEPLOY_MODE=canary-registered              deploy the @challenger Airflow already
//                                              registered (sent by retrain_dag after drift)
//
// Python steps run inside the CI image (infra/ci/Dockerfile), so Jenkins needs
// only Docker; the versions are the same pinned ones the services use.
//
// The canary tests the NEW MODEL (toxicity-svc-canary loads @challenger and gets
// a share of traffic). New service code in the same build rolls out to the stable
// pods as an ordinary rolling update.

pipeline {
  agent any

  parameters {
    choice(name: 'DEPLOY_MODE', choices: ['canary', 'canary-registered', 'set-weight', 'promote', 'rollback', 'none'],
           description: 'What to do after a green build')
    string(name: 'CANARY_WEIGHT', defaultValue: '10', description: 'Percent of traffic for the canary')
    string(name: 'REASON', defaultValue: 'push', description: 'Why this build ran (shown in the build name)')
  }

  environment {
    REGISTRY = 'localhost:5001'
    TAG = "${env.BUILD_NUMBER}"
    // VM_IP is passed to the Jenkins container by infra/cloud/setup-vm.sh (inside a
    // container, `hostname -I` would return the container's address, not the VM's)
    MLFLOW_TRACKING_URI = "http://${env.VM_IP}:5000"
    CI_IMAGE = "moderaguard-ci:${env.BUILD_NUMBER}"
    S3 = credentials('s3-dvc')            // S3_USR / S3_PSW: DVC remote and MLflow artifacts
  }

  options {
    timestamps()
    timeout(time: 60, unit: 'MINUTES')
    buildDiscarder(logRotator(numToKeepStr: '30'))
    disableConcurrentBuilds()
  }

  stages {
    stage('CI image') {
      steps {
        script { currentBuild.displayName = "#${env.BUILD_NUMBER} ${params.DEPLOY_MODE} (${params.REASON})" }
        sh 'docker build -f infra/ci/Dockerfile -t $CI_IMAGE .'
      }
    }

    stage('Lint') {
      when { expression { ['canary', 'none'].contains(params.DEPLOY_MODE) } }
      steps { sh 'docker run --rm -v "$WORKSPACE":/workspace $CI_IMAGE ruff check .' }
    }

    stage('Unit, data, model and API tests') {
      when { expression { ['canary', 'none'].contains(params.DEPLOY_MODE) } }
      steps {
        sh '''docker run --rm -v "$WORKSPACE":/workspace -e MODERAGUARD_DISABLE_MLFLOW=1 $CI_IMAGE \
              pytest --junitxml=reports/junit.xml --cov=moderaguard --cov-report=term'''
      }
      post { always { junit allowEmptyResults: true, testResults: 'reports/junit.xml' } }
    }

    stage('Data checks, training and quality gate') {
      // `dvc repro` runs prepare -> validate -> train -> fairness -> quality_gate.
      // The gate exits non-zero when the challenger is worse or less fair, which stops the build.
      when { expression { ['canary', 'none'].contains(params.DEPLOY_MODE) } }
      steps {
        sh '''docker run --rm -v "$WORKSPACE":/workspace -e MLFLOW_TRACKING_URI=$MLFLOW_TRACKING_URI \
              -e AWS_ACCESS_KEY_ID=$S3_USR -e AWS_SECRET_ACCESS_KEY=$S3_PSW $CI_IMAGE sh -c "
                git config --global --add safe.directory /workspace &&
                dvc remote modify --local storage endpointurl http://$VM_IP:8333 &&
                (dvc pull -q data/raw || echo 'no data in the DVC remote yet: the pipeline uses the sample') &&
                dvc repro && cat reports/gate_toxicity.json"'''
      }
      post { always { archiveArtifacts allowEmptyArchive: true, artifacts: 'reports/*.json, reports/*.md' } }
    }

    stage('Build images') {
      when { expression { ['canary', 'canary-registered', 'none'].contains(params.DEPLOY_MODE) } }
      steps {
        sh '''
          for svc in gateway model-service moderator-ui alert-bridge consumer producer; do
            docker build -f services/$svc/Dockerfile -t $REGISTRY/moderaguard/$svc:$TAG .
          done
        '''
      }
    }

    stage('Security scan (Trivy)') {
      // Fails the build on CRITICAL vulnerabilities that have a fix available.
      when { expression { ['canary', 'canary-registered', 'none'].contains(params.DEPLOY_MODE) } }
      steps {
        sh '''
          for svc in gateway model-service moderator-ui; do
            docker run --rm -v /var/run/docker.sock:/var/run/docker.sock aquasec/trivy:0.65.0 image \
              --severity CRITICAL --ignore-unfixed --exit-code 1 --no-progress $REGISTRY/moderaguard/$svc:$TAG
          done
        '''
      }
    }

    stage('Push images') {
      when { expression { ['canary', 'canary-registered'].contains(params.DEPLOY_MODE) } }
      steps {
        sh '''
          for svc in gateway model-service moderator-ui alert-bridge consumer producer; do
            docker push $REGISTRY/moderaguard/$svc:$TAG
          done
        '''
      }
    }

    stage('Deploy canary') {
      when { expression { ['canary', 'canary-registered'].contains(params.DEPLOY_MODE) } }
      steps {
        withCredentials([file(credentialsId: 'kubeconfig-vm', variable: 'KUBECONFIG_FILE')]) {
          sh '''docker run --rm -v "$WORKSPACE":/workspace -v "$KUBECONFIG_FILE":/kubeconfig:ro \
                -e KUBECONFIG=/kubeconfig -e MLFLOW_TRACKING_URI=$MLFLOW_TRACKING_URI \
                -e REGISTRY=$REGISTRY -e TAG=$TAG -e WEIGHT=$CANARY_WEIGHT -e MODE=$DEPLOY_MODE $CI_IMAGE sh -ec '
            # a challenger that passed the gate in this build becomes models:/moderaguard-toxicity@challenger
            # (canary-registered: Airflow already registered it after retraining)
            if [ "$MODE" = canary ]; then
              python -m moderaguard.models.register register --task toxicity --variant challenger --alias challenger
            fi
            for overlay in cloud canary; do
              cd /workspace/k8s/overlays/$overlay
              for svc in gateway model-service moderator-ui; do
                kustomize edit set image moderaguard/$svc=$REGISTRY/moderaguard/$svc:$TAG
              done
            done
            cd /workspace
            kubectl apply -k k8s/overlays/canary
            kubectl -n moderaguard rollout status deployment/toxicity-svc-canary --timeout=300s
            kubectl -n moderaguard rollout status deployment/gateway-canary --timeout=300s
            k8s/scripts/set-canary-weight.sh $WEIGHT
          ' '''
        }
      }
    }

    stage('Smoke test canary') {
      when { expression { ['canary', 'canary-registered'].contains(params.DEPLOY_MODE) } }
      steps {
        sh '''
          for i in $(seq 1 20); do
            curl -fsS -H "X-Canary: always" http://$VM_IP/ready && break || sleep 5
          done
          curl -fsS -H "X-Canary: always" -H "Content-Type: application/json" \
               -d '{"text": "Thanks for the thoughtful article"}' http://$VM_IP/moderate | tee reports/smoke.json
          grep -q '"variant":"canary"' reports/smoke.json
        '''
      }
    }

    stage('Change canary weight') {
      when { expression { params.DEPLOY_MODE == 'set-weight' } }
      steps {
        withCredentials([file(credentialsId: 'kubeconfig-vm', variable: 'KUBECONFIG_FILE')]) {
          sh 'docker run --rm -v "$WORKSPACE":/workspace -v "$KUBECONFIG_FILE":/kubeconfig:ro -e KUBECONFIG=/kubeconfig $CI_IMAGE k8s/scripts/set-canary-weight.sh $CANARY_WEIGHT'
        }
      }
    }

    stage('Promote or roll back') {
      when { expression { ['promote', 'rollback'].contains(params.DEPLOY_MODE) } }
      steps {
        withCredentials([file(credentialsId: 'kubeconfig-vm', variable: 'KUBECONFIG_FILE')]) {
          sh '''docker run --rm -v "$WORKSPACE":/workspace -v "$KUBECONFIG_FILE":/kubeconfig:ro \
                -e KUBECONFIG=/kubeconfig -e MLFLOW_TRACKING_URI=$MLFLOW_TRACKING_URI $CI_IMAGE \
                k8s/scripts/end-canary.sh $DEPLOY_MODE'''
        }
      }
    }
  }

  post {
    always {
      sh 'docker image rm $CI_IMAGE || true'
    }
  }
}
