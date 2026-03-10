#!/bin/bash
set -e

# ExpertelIQ2 Scraper - AWS Secrets Management Script
# Manages secrets in AWS Systems Manager Parameter Store

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Default configuration
DEFAULT_REGION="us-east-2"
DEFAULT_APP_NAME="experteliq2-scraper"

# -----------------------------------------------------------------------------
# SECRET REGISTRY (single source of truth)
# -----------------------------------------------------------------------------
# Format: "path|type|required|description|prompt"
# type: S = SecureString, P = Plain (String)
# required: R = Required, O = Optional

SECRETS_REGISTRY=(
    "database/password|S|R|PostgreSQL password|PostgreSQL Password"
    "backend-api/key|S|R|Backend API key|Backend API Key"
    "cryptography/key|S|R|Cryptography key|Cryptography Key"
    "azure/client-id|P|R|Azure AD client ID|Azure Client ID"
    "azure/tenant-id|P|R|Azure AD tenant ID|Azure Tenant ID"
    "azure/client-secret|S|R|Azure AD client secret|Azure Client Secret"
    "novnc/password|S|R|noVNC access password|noVNC Password"
    "anthropic/api-key|S|O|Anthropic API key|Anthropic API Key"
    "email/host-user|P|O|SMTP host user|Email SMTP Host User"
    "email/host-password|S|O|SMTP host password|Email SMTP Host Password"
    "slack/webhook-url|S|O|Slack webhook URL|Slack Webhook URL"
    "teams/webhook-url|S|O|Teams webhook URL|Microsoft Teams Webhook URL"
)

# -----------------------------------------------------------------------------
# HELPER FUNCTIONS
# -----------------------------------------------------------------------------

print_header() {
    echo -e "${BLUE}==========================================================${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}==========================================================${NC}"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}! $1${NC}"
}

show_help() {
    echo -e "${BLUE}ExpertelIQ2 Scraper - AWS Secrets Management${NC}"
    echo ""
    echo "Usage: $0 <command> [options]"
    echo ""
    echo "Commands:"
    echo "  setup <env>     - Initial setup of ALL secrets for environment"
    echo "  update <env>    - Update ALL existing secrets for environment"
    echo "  set <env> <key> - Set a single specific secret (interactive prompt)"
    echo "  list <env>      - List all secrets for environment"
    echo "  validate <env>  - Validate required secrets exist"
    echo "  get <env> <key> - Get specific secret value"
    echo "  delete <env>    - Delete all secrets for environment (DANGEROUS!)"
    echo ""
    echo "Options:"
    echo "  --region <region>    AWS region (default: $DEFAULT_REGION)"
    echo "  --app-name <name>    Application name (default: $DEFAULT_APP_NAME)"
    echo ""
    echo "Environments:"
    echo "  dev, qa, prod (or any custom name)"
    echo ""
    echo "SSM Parameters Created:"
    echo "  REQUIRED:"
    for entry in "${SECRETS_REGISTRY[@]}"; do
        IFS='|' read -r path _ req description _ <<< "$entry"
        if [ "$req" = "R" ]; then
            printf "    /{app}/{env}/%-25s - %s\n" "$path" "$description"
        fi
    done
    echo ""
    echo "  OPTIONAL:"
    for entry in "${SECRETS_REGISTRY[@]}"; do
        IFS='|' read -r path _ req description _ <<< "$entry"
        if [ "$req" = "O" ]; then
            printf "    /{app}/{env}/%-25s - %s\n" "$path" "$description"
        fi
    done
    echo ""
    echo "Valid secret keys:"
    local keys=""
    for entry in "${SECRETS_REGISTRY[@]}"; do
        IFS='|' read -r path _ _ _ _ <<< "$entry"
        if [ -n "$keys" ]; then keys="$keys, "; fi
        keys="$keys$path"
    done
    echo "  $keys"
    echo ""
    echo "Examples:"
    echo "  $0 setup dev"
    echo "  $0 set dev database/password"
    echo "  $0 set qa email/host-password"
    echo "  $0 update prod --region us-west-2"
    echo "  $0 list qa"
    echo "  $0 get dev backend-api/key"
}

# -----------------------------------------------------------------------------
# ARGUMENT PARSING
# -----------------------------------------------------------------------------

COMMAND=""
ENVIRONMENT=""
SECRET_KEY=""
REGION="$DEFAULT_REGION"
APP_NAME="$DEFAULT_APP_NAME"

while [[ $# -gt 0 ]]; do
    case $1 in
        setup|update|set|list|validate|get|delete)
            COMMAND=$1
            shift
            ;;
        --region)
            REGION=$2
            shift 2
            ;;
        --app-name)
            APP_NAME=$2
            shift 2
            ;;
        --help|-h)
            show_help
            exit 0
            ;;
        *)
            if [ -z "$ENVIRONMENT" ]; then
                ENVIRONMENT=$1
            elif [ -z "$SECRET_KEY" ]; then
                SECRET_KEY=$1
            else
                print_error "Unknown argument: $1"
                show_help
                exit 1
            fi
            shift
            ;;
    esac
done

# Validate inputs
if [ -z "$COMMAND" ]; then
    print_error "Error: Command is required"
    show_help
    exit 1
fi

if [ -z "$ENVIRONMENT" ] && [ "$COMMAND" != "help" ]; then
    print_error "Error: Environment is required"
    show_help
    exit 1
fi

# Warn for non-standard environments
if [[ "$ENVIRONMENT" != "dev" && "$ENVIRONMENT" != "qa" && "$ENVIRONMENT" != "prod" ]]; then
    print_warning "Warning: Using non-standard environment name: $ENVIRONMENT"
    read -p "Continue? (y/N): " confirm
    if [[ ! $confirm =~ ^[Yy]$ ]]; then
        exit 0
    fi
fi

# Check AWS CLI
if ! command -v aws &> /dev/null; then
    print_error "AWS CLI is not installed"
    echo "Install from: https://aws.amazon.com/cli/"
    exit 1
fi

if ! aws sts get-caller-identity --region "$REGION" &> /dev/null; then
    print_error "AWS credentials not configured or invalid"
    echo "Run: aws configure"
    exit 1
fi

# -----------------------------------------------------------------------------
# AWS SSM FUNCTIONS
# -----------------------------------------------------------------------------

prompt_for_secret() {
    local prompt_text=$1
    local is_sensitive=${2:-true}
    local value=""

    if [ "$is_sensitive" = "true" ]; then
        echo -n "$prompt_text: " >&2
        read -s value
        echo "" >&2
    else
        echo -n "$prompt_text: " >&2
        read value
    fi

    echo "$value"
}

put_parameter() {
    local name=$1
    local value=$2
    local type=${3:-"SecureString"}
    local description=$4

    echo -e "${BLUE}Storing parameter: $name${NC}"

    if aws ssm put-parameter \
        --region "$REGION" \
        --name "$name" \
        --value "$value" \
        --type "$type" \
        --description "$description" \
        --overwrite > /dev/null; then
        print_success "Successfully stored: $name"
    else
        print_error "Failed to store: $name"
        return 1
    fi
}

get_parameter() {
    local name=$1
    aws ssm get-parameter \
        --region "$REGION" \
        --name "$name" \
        --with-decryption \
        --query 'Parameter.Value' \
        --output text 2>/dev/null
}

list_parameters() {
    local path="/$APP_NAME/$ENVIRONMENT"

    echo -e "${BLUE}Parameters for $APP_NAME/$ENVIRONMENT:${NC}"
    echo "================================================"

    aws ssm get-parameters-by-path \
        --region "$REGION" \
        --path "$path" \
        --recursive \
        --query 'Parameters[*].[Name,Type,LastModifiedDate]' \
        --output table
}

delete_parameters() {
    local path="/$APP_NAME/$ENVIRONMENT"

    echo -e "${RED}⚠️  WARNING: This will delete ALL parameters for $APP_NAME/$ENVIRONMENT${NC}"
    echo -e "${RED}This action cannot be undone!${NC}"
    echo ""
    read -p "Type 'DELETE' to confirm: " confirmation

    if [ "$confirmation" != "DELETE" ]; then
        echo "Deletion cancelled."
        return 0
    fi

    local parameters=$(aws ssm get-parameters-by-path \
        --region "$REGION" \
        --path "$path" \
        --recursive \
        --query 'Parameters[*].Name' \
        --output text)

    if [ -z "$parameters" ]; then
        echo "No parameters found to delete."
        return 0
    fi

    for param in $parameters; do
        print_warning "Deleting: $param"
        aws ssm delete-parameter --region "$REGION" --name "$param" || true
    done

    print_success "Deletion completed"
}

# Helper to get registry entry by key
get_registry_entry() {
    local key=$1
    for entry in "${SECRETS_REGISTRY[@]}"; do
        IFS='|' read -r path _ _ _ _ <<< "$entry"
        if [ "$path" = "$key" ]; then
            echo "$entry"
            return 0
        fi
    done
    return 1
}

# Prompt and store a single secret from registry entry
prompt_and_store() {
    local entry=$1
    local prefix="/$APP_NAME/$ENVIRONMENT"

    IFS='|' read -r path type req description prompt_text <<< "$entry"

    local is_sensitive="true"
    local ssm_type="SecureString"
    if [ "$type" = "P" ]; then
        is_sensitive="false"
        ssm_type="String"
    fi

    local label=""
    if [ "$req" = "R" ]; then
        label="(REQUIRED)"
    else
        label="(optional)"
    fi

    local value=$(prompt_for_secret "$prompt_text $label" "$is_sensitive")

    if [ -n "$value" ]; then
        put_parameter "$prefix/$path" "$value" "$ssm_type" "$description"
    elif [ "$req" = "R" ]; then
        print_error "Error: $path is required"
        exit 1
    else
        print_warning "Skipped: $path"
    fi
}

# -----------------------------------------------------------------------------
# MAIN COMMAND EXECUTION
# -----------------------------------------------------------------------------

case $COMMAND in
    setup|update)
        print_header "Setting up secrets for $APP_NAME/$ENVIRONMENT"
        echo ""
        echo -e "${YELLOW}All values will be stored in AWS SSM Parameter Store${NC}"
        echo -e "${YELLOW}Press Enter to skip optional parameters${NC}"
        echo ""

        # Required secrets
        echo -e "${GREEN}--- REQUIRED SECRETS ---${NC}"
        echo ""
        for entry in "${SECRETS_REGISTRY[@]}"; do
            IFS='|' read -r _ _ req _ _ <<< "$entry"
            if [ "$req" = "R" ]; then
                prompt_and_store "$entry"
            fi
        done

        echo ""
        # Optional secrets
        echo -e "${GREEN}--- OPTIONAL SECRETS (press Enter to skip) ---${NC}"
        echo ""
        for entry in "${SECRETS_REGISTRY[@]}"; do
            IFS='|' read -r _ _ req _ _ <<< "$entry"
            if [ "$req" = "O" ]; then
                prompt_and_store "$entry"
            fi
        done

        echo ""
        print_header "Secrets setup completed for $ENVIRONMENT environment"
        echo ""
        echo -e "${BLUE}To verify, run: $0 list $ENVIRONMENT${NC}"
        ;;

    set)
        if [ -z "$SECRET_KEY" ]; then
            print_error "Error: Secret key is required for set command"
            echo "Usage: $0 set <env> <secret-key>"
            echo "Example: $0 set dev database/password"
            echo ""
            echo "Valid keys:"
            for entry in "${SECRETS_REGISTRY[@]}"; do
                IFS='|' read -r path _ _ description _ <<< "$entry"
                printf "  %-25s - %s\n" "$path" "$description"
            done
            exit 1
        fi

        # Validate the secret key against registry
        entry=$(get_registry_entry "$SECRET_KEY") || true
        if [ -z "$entry" ]; then
            print_error "Error: Unknown secret key: $SECRET_KEY"
            echo ""
            echo "Valid keys:"
            for e in "${SECRETS_REGISTRY[@]}"; do
                IFS='|' read -r path _ _ description _ <<< "$e"
                printf "  %-25s - %s\n" "$path" "$description"
            done
            exit 1
        fi

        IFS='|' read -r path type _ description _ <<< "$entry"

        local_is_sensitive="true"
        local_ssm_type="SecureString"
        if [ "$type" = "P" ]; then
            local_is_sensitive="false"
            local_ssm_type="String"
        fi

        param_name="/$APP_NAME/$ENVIRONMENT/$SECRET_KEY"
        echo -e "${BLUE}Setting secret: $param_name${NC}"
        secret_value=$(prompt_for_secret "Enter value for $SECRET_KEY" "$local_is_sensitive")

        if [ -z "$secret_value" ]; then
            print_error "Error: Value cannot be empty"
            exit 1
        fi

        put_parameter "$param_name" "$secret_value" "$local_ssm_type" "$description"
        echo ""
        print_success "Secret $SECRET_KEY updated for $ENVIRONMENT environment"
        ;;

    list)
        list_parameters
        ;;

    validate)
        print_header "Validating secrets for $ENVIRONMENT environment"

        local_prefix="/$APP_NAME/$ENVIRONMENT"
        all_valid=true

        echo ""
        echo "Required secrets:"
        for entry in "${SECRETS_REGISTRY[@]}"; do
            IFS='|' read -r path _ req _ _ <<< "$entry"
            if [ "$req" = "R" ]; then
                value=$(get_parameter "$local_prefix/$path")
                if [ -n "$value" ]; then
                    print_success "$path"
                else
                    print_error "$path (MISSING)"
                    all_valid=false
                fi
            fi
        done

        echo ""
        echo "Optional secrets:"
        for entry in "${SECRETS_REGISTRY[@]}"; do
            IFS='|' read -r path _ req _ _ <<< "$entry"
            if [ "$req" = "O" ]; then
                value=$(get_parameter "$local_prefix/$path")
                if [ -n "$value" ]; then
                    print_success "$path"
                else
                    print_warning "$path (not set)"
                fi
            fi
        done

        echo ""
        if [ "$all_valid" = true ]; then
            print_success "All required secrets are configured"
            exit 0
        else
            print_error "Some required secrets are missing"
            exit 1
        fi
        ;;

    get)
        if [ -z "$SECRET_KEY" ]; then
            print_error "Error: Secret key is required for get command"
            echo "Usage: $0 get <env> <secret-key>"
            echo "Example: $0 get dev database/password"
            exit 1
        fi

        param_name="/$APP_NAME/$ENVIRONMENT/$SECRET_KEY"
        value=$(get_parameter "$param_name")

        if [ -n "$value" ]; then
            print_success "Parameter: $param_name"
            echo "Value: $value"
        else
            print_error "Parameter not found: $param_name"
            exit 1
        fi
        ;;

    delete)
        delete_parameters
        ;;

    *)
        print_error "Unknown command: $COMMAND"
        show_help
        exit 1
        ;;
esac