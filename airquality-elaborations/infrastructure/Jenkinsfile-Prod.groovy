pipeline {
    agent any

    environment {
        SERVER_PORT="1002"
        PROJECT = "airquality-elaborations"
        PROJECT_FOLDER = "${PROJECT}"
        ARTIFACT_NAME = "${PROJECT}"
        DOCKER_IMAGE = '755952719952.dkr.ecr.eu-west-1.amazonaws.com/airquality-elaborations'
        DOCKER_TAG = "prod-$BUILD_NUMBER"
        DATACOLLECTORS_CLIENT_SECRET = credentials('keycloak-datacollectors-secret-prod')
        ELABORATIONS_CLIENT_SECRET = credentials('keycloak-elaborations-secret-prod')
    }

    stages {
        stage('Configure') {
            steps {
                sh """
                    cd ${PROJECT_FOLDER}
                    echo 'COMPOSE_PROJECT_NAME=${PROJECT}' > .env
                    echo 'SERVER_PORT=${SERVER_PORT}' >> .env
                    echo 'DOCKER_IMAGE=${DOCKER_IMAGE}' >> .env
                    echo 'DOCKER_TAG=${DOCKER_TAG}' >> .env
                    echo 'LOG_LEVEL=debug' >> .env
                    echo 'ARTIFACT_NAME=${ARTIFACT_NAME}' >> .env
                    echo 'origin=a22-algorab' >> .env
                    echo 'authorizationUri=https://auth.opendatahub.bz.it/auth' >> .env
                    echo 'tokenUri=https://auth.opendatahub.bz.it/auth/realms/noi/protocol/openid-connect/token' >> .env
                    echo 'base-uri=https://mobility.share.opendatahub.bz.it/json' >> .env
                    echo 'clientId=odh-mobility-datacollector' >> .env
                    echo 'clientName=odh-mobility-datacollector' >> .env
                    echo 'clientSecret=${DATACOLLECTORS_CLIENT_SECRET}' >> .env
                    echo 'NINJA_CLIENT=odh-mobility-airquality-elaboration' >> .env
                    echo 'NINJA_SECRET=${ELABORATIONS_CLIENT_SECRET}' >> .env
                    echo 'ODH_BASE_URI=https://mobility.api.opendatahub.bz.it/' >> .env
                    echo 'scope=openid' >> .env
                    echo 'stationtype=EnvironmentStation' >> .env
                    echo -n 'provenance_version=' >> .env
                    xmlstarlet sel -N pom=http://maven.apache.org/POM/4.0.0 -t -v '/pom:project/pom:version' pom.xml >> .env
                    echo '' >> .env
                    echo -n 'provenance_name=' >> .env
                    xmlstarlet sel -N pom=http://maven.apache.org/POM/4.0.0 -t -v '/pom:project/pom:artifactId' pom.xml >> .env
                    echo '' >> .env
                """
            }
        }
        stage('Test & Build') {
            steps {
                sh """
                    cd ${PROJECT_FOLDER}
                    aws ecr get-login --region eu-west-1 --no-include-email | bash
                    docker-compose --no-ansi -f infrastructure/docker-compose.build.yml build --pull
                    docker-compose --no-ansi -f infrastructure/docker-compose.build.yml push
                """
            }
        }
        stage('Deploy') {
            steps {
               sshagent(['jenkins-ssh-key']) {
                    sh """
                        (cd ${PROJECT_FOLDER}/infrastructure/ansible && ansible-galaxy install -f -r requirements.yml)
                        (cd ${PROJECT_FOLDER}/infrastructure/ansible && ansible-playbook --limit=prod deploy.yml --extra-vars "release_name=${BUILD_NUMBER} project_name=${PROJECT}")
                    """
                }
            }
        }
    }
}
